"""Scanner request signing and biometric attestation route tests."""
from __future__ import annotations

import json
import time
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import biometric_routes
from db import ScannerRequestNonce, SessionLocal, init_db
from scanner_auth import create_scanner_signature, verify_scanner_request


TEST_SECRET = "scanner-test-secret-material-at-least-32-bytes"


@pytest.fixture
def db_session():
    init_db()
    session = SessionLocal()
    session.query(ScannerRequestNonce).delete()
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(biometric_routes.router)

    def _db_override():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[biometric_routes.get_db] = _db_override
    return TestClient(app)


def _payload_body() -> bytes:
    payload = {
        "badge_serial": "TEST-BADGE-001",
        "face_scan_hex": "00",
        "retina_scan_hex": "11",
        "liveness_score": 0.99,
        "location_node": "test-node-001",
        "action_type": "proposal",
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _signed_headers(body: bytes, secret: str = TEST_SECRET, nonce: str | None = None):
    timestamp = str(int(time.time()))
    nonce = nonce or uuid.uuid4().hex
    signature = create_scanner_signature(
        body=body,
        timestamp=timestamp,
        nonce=nonce,
        secret=secret,
    )
    return {
        "Content-Type": "application/json",
        "X-Scanner-Timestamp": timestamp,
        "X-Scanner-Nonce": nonce,
        "X-Scanner-Signature": signature,
    }


def test_valid_signature_claims_nonce_and_duplicate_is_rejected(db_session, monkeypatch):
    body = _payload_body()
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    signature = create_scanner_signature(
        body=body,
        timestamp=timestamp,
        nonce=nonce,
        secret=TEST_SECRET,
    )
    common = {
        "timestamp": timestamp,
        "nonce": nonce,
        "signature": signature,
        "body": body,
        "secret": TEST_SECRET,
    }

    valid, reason = verify_scanner_request(db_session, **common)
    assert valid is True
    assert reason == "OK"

    replayed, replay_reason = verify_scanner_request(db_session, **common)
    assert replayed is False
    assert replay_reason == "nonce_replayed"
    assert db_session.query(ScannerRequestNonce).count() == 1


def test_tampered_body_is_rejected_without_claiming_nonce(db_session):
    body = _payload_body()
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    signature = create_scanner_signature(
        body=body,
        timestamp=timestamp,
        nonce=nonce,
        secret=TEST_SECRET,
    )
    ok, reason = verify_scanner_request(
        db_session,
        timestamp=timestamp,
        nonce=nonce,
        signature=signature,
        body=body + b" ",
        secret=TEST_SECRET,
    )
    assert ok is False
    assert reason == "signature_mismatch"
    assert db_session.query(ScannerRequestNonce).count() == 0


def test_stale_timestamp_is_rejected(db_session):
    body = _payload_body()
    timestamp = str(int(time.time()) - 300)
    nonce = uuid.uuid4().hex
    signature = create_scanner_signature(
        body=body,
        timestamp=timestamp,
        nonce=nonce,
        secret=TEST_SECRET,
    )
    ok, reason = verify_scanner_request(
        db_session,
        timestamp=timestamp,
        nonce=nonce,
        signature=signature,
        body=body,
        secret=TEST_SECRET,
    )
    assert ok is False
    assert reason == "timestamp_outside_window"
    assert db_session.query(ScannerRequestNonce).count() == 0


def test_missing_or_short_secret_fails_closed(db_session):
    ok, reason = verify_scanner_request(
        db_session,
        timestamp=str(int(time.time())),
        nonce=uuid.uuid4().hex,
        signature="0" * 64,
        body=_payload_body(),
        secret="too-short",
    )
    assert ok is False
    assert reason == "scanner_auth_not_configured"


def test_route_rejects_missing_signature_before_biometric_issuance(client, monkeypatch):
    monkeypatch.setenv("COLONY_SCANNER_HMAC_SECRET", TEST_SECRET)
    issue = MagicMock(return_value={"token_id": "should-not-be-issued"})
    monkeypatch.setattr(biometric_routes, "issue_attestation", issue)

    response = client.post("/biometric/attest", content=_payload_body(), headers={
        "Content-Type": "application/json",
    })

    assert response.status_code == 401
    assert issue.call_count == 0


def test_route_accepts_signed_request_once_and_rejects_replay(client, monkeypatch):
    monkeypatch.setenv("COLONY_SCANNER_HMAC_SECRET", TEST_SECRET)
    issue = MagicMock(return_value={
        "token_id": "token-fixture",
        "member_id": "member-fixture",
        "duress_triggered": False,
    })
    monkeypatch.setattr(biometric_routes, "issue_attestation", issue)

    body = _payload_body()
    headers = _signed_headers(body)
    first = client.post("/biometric/attest", content=body, headers=headers)
    second = client.post("/biometric/attest", content=body, headers=headers)

    assert first.status_code == 200
    assert first.json()["status"] == "issued"
    assert "duress_triggered" not in first.json()["token"]
    assert second.status_code == 401
    assert issue.call_count == 1


def test_route_returns_service_unavailable_when_secret_is_not_configured(client, monkeypatch):
    monkeypatch.delenv("COLONY_SCANNER_HMAC_SECRET", raising=False)
    issue = MagicMock(return_value={"token_id": "should-not-be-issued"})
    monkeypatch.setattr(biometric_routes, "issue_attestation", issue)

    response = client.post("/biometric/attest", content=_payload_body(), headers={
        "Content-Type": "application/json",
    })

    assert response.status_code == 503
    assert issue.call_count == 0
