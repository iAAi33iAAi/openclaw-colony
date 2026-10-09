"""Ed25519 verification for signed Knowledge Contracts.

The trust store is supplied by the host. No permissive or self-trusting default exists.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .contracts import KnowledgeContract, SignedKnowledgeContract
from .verification import canonical_json_bytes, sha256_hex


class ContractTrustError(ValueError):
    """Raised when a Knowledge Contract cannot be authenticated."""


@dataclass(frozen=True)
class VerifiedContract:
    contract: KnowledgeContract
    signer_key_id: str
    contract_digest: str


def _contract_payload(contract: KnowledgeContract) -> dict:
    payload = contract.model_dump(mode="json")
    # JSON arrays backed by sets must have stable ordering across processes.
    for field in (
        "approved_model_digests",
        "approved_source_ids",
        "permitted_sensor_ids",
        "allowed_targets",
        "allowed_recommendations",
        "prohibited_actions",
    ):
        value = payload.get(field)
        if isinstance(value, list):
            payload[field] = sorted(value)
    return payload


def contract_digest(contract: KnowledgeContract) -> str:
    return sha256_hex(canonical_json_bytes(_contract_payload(contract)))


def contract_signing_payload(envelope: SignedKnowledgeContract) -> bytes:
    """Bytes signed by the issuer; signature bytes are deliberately excluded."""
    digest = contract_digest(envelope.contract)
    return canonical_json_bytes({
        "schema": "AETHEL-KNOWLEDGE-CONTRACT-ED25519-v1",
        "signer_key_id": envelope.signer_key_id,
        "issued_at_utc": envelope.issued_at_utc.isoformat(),
        "contract_digest": digest,
    })


class Ed25519ContractVerifier:
    """Verify envelopes against explicitly configured trust anchors and revocations.

    Public keys are raw 32-byte Ed25519 keys, keyed by stable key ID. Updating this
    object is a host trust-store operation; a contract cannot introduce its own key.
    """

    def __init__(
        self,
        *,
        trusted_public_keys: Mapping[str, bytes],
        revoked_key_ids: frozenset[str] = frozenset(),
        clock_skew_seconds: int = 30,
    ):
        if clock_skew_seconds < 0 or clock_skew_seconds > 300:
            raise ValueError("clock_skew_seconds must be in [0, 300]")
        self._trusted_public_keys = dict(trusted_public_keys)
        self._revoked_key_ids = frozenset(revoked_key_ids)
        self._clock_skew = timedelta(seconds=clock_skew_seconds)

    def verify(self, envelope: SignedKnowledgeContract, *, now: datetime) -> VerifiedContract:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        now = now.astimezone(timezone.utc)

        if envelope.signature_algorithm != "Ed25519":
            raise ContractTrustError("contract_signature_algorithm_unsupported")
        key_id = envelope.signer_key_id
        if key_id in self._revoked_key_ids:
            raise ContractTrustError("contract_signer_revoked")
        public_key_bytes = self._trusted_public_keys.get(key_id)
        if public_key_bytes is None:
            raise ContractTrustError("contract_signer_untrusted")
        if len(public_key_bytes) != 32:
            raise ContractTrustError("trust_anchor_malformed")
        if envelope.issued_at_utc > now + self._clock_skew:
            raise ContractTrustError("contract_issued_in_future")
        if envelope.issued_at_utc >= envelope.contract.valid_until_utc:
            raise ContractTrustError("contract_issued_after_expiry")

        try:
            signature = base64.b64decode(envelope.signature_b64, validate=True)
            public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
            public_key.verify(signature, contract_signing_payload(envelope))
        except (binascii.Error, ValueError, InvalidSignature) as exc:
            raise ContractTrustError("contract_signature_invalid") from exc

        return VerifiedContract(
            contract=envelope.contract,
            signer_key_id=key_id,
            contract_digest=contract_digest(envelope.contract),
        )
