"""Trust-boundary helpers. Default signature verification rejects all signatures."""
from __future__ import annotations
import hashlib
import json
from typing import Any, Protocol
import hmac

class SignatureVerifier(Protocol):
    def verify(self, *, key_id: str, message: bytes, signature: str) -> bool: ...

class RejectAllSignatures:
    """Safe default: no telemetry signature is trusted without configuration."""
    def verify(self, *, key_id: str, message: bytes, signature: str) -> bool:
        return False

def canonical_json_bytes(value: Any) -> bytes:
    """Project-local deterministic JSON profile; not claimed as RFC 8785."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()



def verify_inspection_result_integrity(result: "InspectionResult") -> bool:
    """Recompute the advisory record digest; this is integrity checking, not a signature."""
    from .contracts import InspectionResult

    if not isinstance(result, InspectionResult):
        return False
    body = {
        "request_id": result.request_id,
        "decision": result.decision.value,
        "reasons": sorted(set(result.reasons)),
        "proposal": result.proposal.model_dump(mode="json") if result.proposal else None,
        "contract_id": result.contract_id,
        "contract_version": result.contract_version,
        "model_digest": result.model_digest,
        "contract_digest": result.contract_digest,
        "policy_id": result.policy_id,
        "created_at_utc": result.created_at_utc.isoformat(),
    }
    expected = sha256_hex(canonical_json_bytes(body))
    return hmac.compare_digest(expected, result.record_digest)
