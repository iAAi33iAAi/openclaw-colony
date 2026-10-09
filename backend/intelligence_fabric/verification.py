"""Trust-boundary helpers. Default signature verification rejects all signatures."""
from __future__ import annotations
import hashlib
import json
from typing import Any, Protocol

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
