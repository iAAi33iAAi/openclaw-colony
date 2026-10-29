"""Reference signer for clients that submit biometric scanner attestations.

This module only signs the exact request body bytes and returns headers. It
does not capture biometrics, transmit HTTP requests, or store/provision secrets.
The scanner's secret must be injected out-of-band into the trusted scanner
process and must never be committed to the repository.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

SCANNER_ATTESTATION_METHOD = "POST"
SCANNER_ATTESTATION_PATH = "/biometric/attest"
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def build_attestation_auth_headers(
    *,
    body: bytes,
    secret: str,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """Return HMAC auth headers for the exact raw request bytes.

    Pass the same body bytes to the HTTP client's content/raw-body argument;
    do not reserialize the JSON after these headers have been generated.
    """
    if not isinstance(body, bytes):
        raise TypeError("body must be the exact bytes sent over HTTP")
    if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
        raise ValueError("scanner secret must contain at least 32 UTF-8 bytes")

    timestamp = str(int(time.time())) if timestamp is None else timestamp
    if not isinstance(timestamp, str) or not re.fullmatch(r"\d{10}", timestamp):
        raise ValueError("timestamp must be a 10-digit Unix timestamp in seconds")

    nonce = secrets.token_urlsafe(24) if nonce is None else nonce
    if not isinstance(nonce, str) or not _NONCE_RE.fullmatch(nonce):
        raise ValueError("nonce must be 16-128 URL-safe characters")

    body_digest = hashlib.sha256(body).hexdigest()
    message = (
        f"{SCANNER_ATTESTATION_METHOD}\n"
        f"{SCANNER_ATTESTATION_PATH}\n"
        f"{timestamp}\n"
        f"{nonce}\n"
        f"{body_digest}"
    ).encode("utf-8")
    signature = hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()

    return {
        "X-Scanner-Timestamp": timestamp,
        "X-Scanner-Nonce": nonce,
        "X-Scanner-Signature": signature,
    }
