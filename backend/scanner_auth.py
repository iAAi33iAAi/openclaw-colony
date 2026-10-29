"""HMAC request authentication for the physical biometric scanner.

The scanner secret is configured out-of-band as COLONY_SCANNER_HMAC_SECRET.
No request body, biometric value, signature secret, or full nonce is logged.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db import ScannerRequestNonce

SCANNER_ATTESTATION_PATH = "/biometric/attest"
DEFAULT_MAX_CLOCK_SKEW_SECONDS = 60
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_SIGNATURE_RE = re.compile(r"^[a-fA-F0-9]{64}$")


def _signed_message(
    *,
    timestamp: str,
    nonce: str,
    body: bytes,
    method: str = "POST",
    path: str = SCANNER_ATTESTATION_PATH,
) -> bytes:
    body_digest = hashlib.sha256(body).hexdigest()
    return f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_digest}".encode("utf-8")


def create_scanner_signature(
    *,
    body: bytes,
    timestamp: str,
    nonce: str,
    secret: str,
    method: str = "POST",
    path: str = SCANNER_ATTESTATION_PATH,
) -> str:
    """Create a test/client signature over the exact HTTP body bytes."""
    if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
        raise ValueError("scanner secret must contain at least 32 UTF-8 bytes")
    message = _signed_message(
        timestamp=timestamp,
        nonce=nonce,
        body=body,
        method=method,
        path=path,
    )
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_scanner_request(
    db: Session,
    *,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
    body: bytes,
    secret: str | None = None,
    now_epoch: float | None = None,
    max_clock_skew_seconds: int = DEFAULT_MAX_CLOCK_SKEW_SECONDS,
) -> tuple[bool, str]:
    """Verify signature, timestamp and durable single-use nonce; fail closed."""
    if secret is None:
        secret = os.environ.get("COLONY_SCANNER_HMAC_SECRET", "")
    if not secret or len(secret.encode("utf-8")) < 32:
        return False, "scanner_auth_not_configured"
    if not isinstance(timestamp, str) or not re.fullmatch(r"\d{10}", timestamp):
        return False, "invalid_timestamp"
    if not isinstance(nonce, str) or not _NONCE_RE.fullmatch(nonce):
        return False, "invalid_nonce"
    if not isinstance(signature, str) or not _SIGNATURE_RE.fullmatch(signature):
        return False, "invalid_signature"
    if not isinstance(body, bytes):
        return False, "invalid_body"

    try:
        issued_epoch = int(timestamp)
    except ValueError:
        return False, "invalid_timestamp"

    now_value = time.time() if now_epoch is None else float(now_epoch)
    if abs(now_value - issued_epoch) > max_clock_skew_seconds:
        return False, "timestamp_outside_window"

    expected = hmac.new(
        secret.encode("utf-8"),
        _signed_message(timestamp=timestamp, nonce=nonce, body=body),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature.lower(), expected):
        return False, "signature_mismatch"

    # Store a hash instead of the supplied nonce. Keep records at least twice
    # the accepted clock-skew window; older signed requests are already stale.
    now_dt = datetime.fromtimestamp(now_value, tz=timezone.utc)
    cutoff = now_dt - timedelta(seconds=max_clock_skew_seconds * 2)
    nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()

    try:
        db.query(ScannerRequestNonce).filter(
            ScannerRequestNonce.created_at < cutoff
        ).delete(synchronize_session=False)
        db.add(
            ScannerRequestNonce(
                nonce_hash=nonce_hash,
                signed_at=datetime.fromtimestamp(issued_epoch, tz=timezone.utc),
                created_at=now_dt,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        return False, "nonce_replayed"
    except Exception:
        db.rollback()
        return False, "nonce_store_unavailable"

    return True, "OK"
