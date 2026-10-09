"""HTTP boundary tests for scanner authentication on biometric attestation."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import biometric_routes as routes
from db import get_db


SCANNER_TOKEN = "scanner-token-for-tests-with-at-least-32-characters"
ATTEST_REQUEST = {
    "badge_serial": "BADGE-TEST-001",
    "face_scan_hex": "66616365",
    "retina_scan_hex": "726574696e61",
    "liveness_score": 0.99,
    "location_node": "test-node-001",
    "action_type": "proposal",
}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_attest_fails_closed_when_scanner_secret_is_missing(client, monkeypatch):
    monkeypatch.delenv("COLONY_SCANNER_BEARER_TOKEN", raising=False)
    issue = Mock()
    monkeypatch.setattr(routes, "issue_attestation", issue)

    response = client.post("/biometric/attest", json=ATTEST_REQUEST)

    assert response.status_code == 503
    assert issue.call_count == 0


def test_attest_fails_closed_when_scanner_secret_is_too_short(client, monkeypatch):
    monkeypatch.setenv("COLONY_SCANNER_BEARER_TOKEN", "weak-secret")
    issue = Mock()
    monkeypatch.setattr(routes, "issue_attestation", issue)

    response = client.post(
        "/biometric/attest",
        json=ATTEST_REQUEST,
        headers={"Authorization": "Bearer weak-secret"},
    )

    assert response.status_code == 503
    assert issue.call_count == 0


def test_attest_rejects_missing_and_wrong_scanner_credentials(client, monkeypatch):
    monkeypatch.setenv("COLONY_SCANNER_BEARER_TOKEN", SCANNER_TOKEN)
    issue = Mock()
    monkeypatch.setattr(routes, "issue_attestation", issue)

    missing = client.post("/biometric/attest", json=ATTEST_REQUEST)
    wrong = client.post(
        "/biometric/attest",
        json=ATTEST_REQUEST,
        headers={"Authorization": "Bearer incorrect-scanner-token"},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert issue.call_count == 0


def test_attest_accepts_configured_scanner_and_hides_duress_flag(client, monkeypatch):
    monkeypatch.setenv("COLONY_SCANNER_BEARER_TOKEN", SCANNER_TOKEN)
    token = {
        "token_id": "test-attestation-id",
        "badge_serial": ATTEST_REQUEST["badge_serial"],
        "duress_triggered": True,
        "hmac_signature": "test-signature",
    }
    issue = Mock(return_value=token)
    monkeypatch.setattr(routes, "issue_attestation", issue)

    response = client.post(
        "/biometric/attest",
        json=ATTEST_REQUEST,
        headers={"Authorization": f"Bearer {SCANNER_TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "issued"
    assert response.json()["token"]["token_id"] == "test-attestation-id"
    assert "duress_triggered" not in response.json()["token"]
    issue.assert_called_once()
    assert issue.call_args.kwargs["face_scan_bytes"] == b"face"
    assert issue.call_args.kwargs["retina_scan_bytes"] == b"retina"
