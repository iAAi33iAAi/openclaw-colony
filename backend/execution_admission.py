"""Short-lived, gate-bound admission receipts for live MANNA transfers.

The receipt is an application-layer interlock, not a hardware-backed attestation.
Production deployments must protect COLONY_EXECUTION_ADMISSION_SECRET and keep it
separate from the biometric-signing secret. Stronger isolation requires a separate
signing service/HSM inaccessible to the process that invokes Stripe.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

ADMISSION_SCHEMA = "colony-execution-admission/v1"
MAX_ADMISSION_TTL_SECONDS = 60


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _signing_material() -> bytes | None:
    raw = os.environ.get("COLONY_EXECUTION_ADMISSION_SECRET", "")
    if len(raw) < 32:
        return None
    biometric_key = os.environ.get("COLONY_BAS_SECRET", "")
    if biometric_key and hmac.compare_digest(raw, biometric_key):
        return None
    return raw.encode("utf-8")


def _sha256_hex(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def issue_execution_admission(
    aethel_result: dict[str, Any],
    payment_claims: dict[str, Any],
    *,
    now_epoch: int | None = None,
    ttl_seconds: int = MAX_ADMISSION_TTL_SECONDS,
) -> dict[str, Any]:
    """Sign payment claims only when all four AETHEL gates explicitly passed."""
    material = _signing_material()
    if material is None:
        raise ValueError(
            "COLONY_EXECUTION_ADMISSION_SECRET must be configured as a distinct "
            "random value of at least 32 characters before live transfers."
        )
    if not isinstance(aethel_result, dict) or aethel_result.get("verdict") != "APPROVED":
        raise ValueError("AETHEL result is not APPROVED.")
    if not isinstance(payment_claims, dict):
        raise ValueError("payment claims must be an object.")
    if not 1 <= ttl_seconds <= MAX_ADMISSION_TTL_SECONDS:
        raise ValueError("admission TTL is outside the permitted range.")

    gates = aethel_result.get("gates")
    if not isinstance(gates, dict):
        raise ValueError("AETHEL gate evidence is missing.")

    # Live money movement always requires biometric Gate 0, even when the
    # application allows Gate 0 bypass for an explicitly configured dev flow.
    required_gates = ("gate_0", "gate_1", "gate_2", "gate_3")
    gate_snapshot: dict[str, Any] = {}
    for gate_name in required_gates:
        gate = gates.get(gate_name)
        if not isinstance(gate, dict) or gate.get("verdict") != "PASS":
            raise ValueError(f"{gate_name} did not explicitly PASS.")
        gate_snapshot[gate_name] = gate

    required_claims = {
        "schema", "task_id", "lineage_hash", "currency",
        "total_cents", "split", "destinations",
    }
    if not required_claims.issubset(payment_claims):
        raise ValueError("payment claims are incomplete.")
    if payment_claims.get("schema") != "colony-manna-payment-claims/v1":
        raise ValueError("unsupported payment-claims schema.")
    if not isinstance(payment_claims.get("task_id"), str) or not payment_claims["task_id"]:
        raise ValueError("task_id is required.")
    if not _sha256_hex(payment_claims.get("lineage_hash")):
        raise ValueError("lineage_hash must be a SHA-256 hex digest.")
    total = payment_claims.get("total_cents")
    if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
        raise ValueError("total_cents must be a positive integer.")
    if payment_claims.get("currency") != "usd":
        raise ValueError("only the explicitly configured USD payment rail is accepted.")
    if not isinstance(payment_claims.get("split"), dict) or not isinstance(payment_claims.get("destinations"), dict):
        raise ValueError("split and destinations must be objects.")

    now = int(time.time()) if now_epoch is None else int(now_epoch)
    payload = {
        "schema": ADMISSION_SCHEMA,
        "decision": "APPROVED",
        "issued_at": now,
        "expires_at": now + ttl_seconds,
        "nonce": str(uuid.uuid4()),
        "gate_digest": hashlib.sha256(_canonical_json(gate_snapshot).encode("utf-8")).hexdigest(),
        "claims": payment_claims,
    }
    signature = hmac.new(
        material, _canonical_json(payload).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {"payload": payload, "signature": signature}


def verify_execution_admission(
    receipt: Any,
    expected_claims: dict[str, Any],
    *,
    now_epoch: int | None = None,
) -> tuple[bool, str]:
    """Verify signature, gate-bound schema, freshness and exact payment claims."""
    material = _signing_material()
    if material is None:
        return False, "execution-admission signing material is missing or not distinct."
    if not isinstance(receipt, dict):
        return False, "signed execution-admission receipt is required."
    payload = receipt.get("payload")
    signature = receipt.get("signature")
    if not isinstance(payload, dict) or not _sha256_hex(signature):
        return False, "execution-admission receipt is malformed."
    try:
        expected_signature = hmac.new(
            material, _canonical_json(payload).encode("utf-8"), hashlib.sha256
        ).hexdigest()
    except (TypeError, ValueError, OverflowError):
        return False, "execution-admission receipt cannot be canonically encoded."
    if not hmac.compare_digest(expected_signature, signature):
        return False, "execution-admission signature mismatch."

    if payload.get("schema") != ADMISSION_SCHEMA or payload.get("decision") != "APPROVED":
        return False, "execution-admission schema or decision is invalid."
    issued_at = payload.get("issued_at")
    expires_at = payload.get("expires_at")
    if (
        isinstance(issued_at, bool) or not isinstance(issued_at, int)
        or isinstance(expires_at, bool) or not isinstance(expires_at, int)
    ):
        return False, "execution-admission timestamps are invalid."
    now = int(time.time()) if now_epoch is None else int(now_epoch)
    if issued_at > now + 5 or expires_at < now or expires_at <= issued_at:
        return False, "execution-admission receipt is expired or not yet valid."
    if expires_at - issued_at > MAX_ADMISSION_TTL_SECONDS:
        return False, "execution-admission TTL exceeds the permitted limit."
    if not isinstance(payload.get("nonce"), str) or not payload["nonce"]:
        return False, "execution-admission nonce is missing."
    if not _sha256_hex(payload.get("gate_digest")):
        return False, "execution-admission gate digest is invalid."
    if payload.get("claims") != expected_claims:
        return False, "execution-admission claims do not match this payment."
    return True, "OK"
