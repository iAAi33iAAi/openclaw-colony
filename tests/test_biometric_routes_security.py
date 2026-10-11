"""Security tests for the authenticated scanner attestation boundary."""
import hashlib
import hmac
import json
import os
import sys
import time

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import biometric_routes as routes
from biometric_routes import AttestRequest
from db import Base


def _request(**overrides):
    fields = {
        "scanner_id": "scanner-001",
        "badge_serial": "BADGE-TEST",
        "face_scan_hex": "aabb",
        "retina_scan_hex": "ccdd",
        "liveness_score": 0.99,
        "location_node": "node-001",
        "action_type": "proposal",
    }
    fields.update(overrides)
    return AttestRequest(**fields)


def _signature(req, secret, timestamp, nonce):
    return hmac.new(
        secret.encode("utf-8"),
        routes._scanner_signature_message(req, timestamp, nonce),
        hashlib.sha256,
    ).hexdigest()


def test_scanner_auth_requires_configured_device_key(monkeypatch):
    monkeypatch.delenv("COLONY_SCANNER_KEYS", raising=False)
    req = _request()
    with pytest.raises(HTTPException) as exc:
        routes._verify_scanner_signature(
            req, str(int(time.time())), "n" * 32, "0" * 64
        )
    assert exc.value.status_code == 401


def test_scanner_signature_uses_actual_newline_delimiters():
    req = _request()
    timestamp = "1791686400"
    nonce = "nonce-with-at-least-16-chars"
    body = json.dumps(
        routes._attestation_body(req),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    expected = (timestamp + chr(10) + nonce + chr(10) + body).encode("utf-8")
    actual = routes._scanner_signature_message(req, timestamp, nonce)

    assert actual == expected
    assert actual.startswith(timestamp.encode("ascii") + b"\n" + nonce.encode("utf-8") + b"\n")


def test_scanner_signature_authenticates_liveness_and_body(monkeypatch):
    secret = "scanner-test-secret-" + ("x" * 40)
    monkeypatch.setenv("COLONY_SCANNER_KEYS", json.dumps({"scanner-001": secret}))
    timestamp = str(int(time.time()))
    nonce = "nonce-for-test-000000000001"
    req = _request()
    sig = _signature(req, secret, timestamp, nonce)

    # Valid signed scanner claim is accepted.
    routes._verify_scanner_signature(req, timestamp, nonce, sig)

    # Changing liveness after signing invalidates the signature.
    tampered = _request(liveness_score=0.01)
    with pytest.raises(HTTPException) as exc:
        routes._verify_scanner_signature(tampered, timestamp, nonce, sig)
    assert exc.value.status_code == 401


def test_attest_request_rejects_nonfinite_liveness_scores():
    from pydantic import ValidationError

    for score in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            _request(liveness_score=score)


def test_placeholder_scanner_secret_is_not_accepted(monkeypatch):
    placeholder = "replace-with-" + ("x" * 40)
    monkeypatch.setenv("COLONY_SCANNER_KEYS", json.dumps({"scanner-001": placeholder}))
    req = _request()
    with pytest.raises(HTTPException) as exc:
        routes._verify_scanner_signature(
            req,
            str(int(time.time())),
            "nonce-placeholder-check-0001",
            "0" * 64,
        )
    assert exc.value.status_code == 401


def test_scanner_signature_rejects_expired_timestamp(monkeypatch):
    secret = "scanner-test-secret-" + ("x" * 40)
    monkeypatch.setenv("COLONY_SCANNER_KEYS", json.dumps({"scanner-001": secret}))
    req = _request()
    timestamp = str(1_700_000_000)
    nonce = "nonce-for-test-000000000002"
    sig = _signature(req, secret, timestamp, nonce)
    with pytest.raises(HTTPException) as exc:
        routes._verify_scanner_signature(
            req, timestamp, nonce, sig, now_epoch=1_700_000_100
        )
    assert exc.value.status_code == 401


def test_scanner_nonce_is_single_use(tmp_path):
    # Isolated test database; nonce persistence must work independently of app DB state.
    engine = create_engine(f"sqlite:///{tmp_path / 'scanner-replay.sqlite'}")
    Base.metadata.create_all(bind=engine)
    req = _request()
    timestamp = str(int(time.time()))
    nonce = "nonce-for-test-single-use-0001"
    with Session(engine) as db:
        routes._consume_scanner_nonce(db, req, timestamp, nonce)
        with pytest.raises(HTTPException) as exc:
            routes._consume_scanner_nonce(db, req, timestamp, nonce)
        assert exc.value.status_code == 409
    engine.dispose()
