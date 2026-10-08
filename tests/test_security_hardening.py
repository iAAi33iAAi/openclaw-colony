"""Security hardening tests for production guardrails."""

import os
import sys

import pytest

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
for path in [BACKEND, os.path.join(BACKEND, "colony-agents"), os.path.join(BACKEND, "love-quality")]:
    if path not in sys.path:
        sys.path.insert(0, path)


def test_auth_cannot_be_disabled_in_production(monkeypatch):
    monkeypatch.setenv("COLONY_ENV", "production")
    monkeypatch.setenv("COLONY_AUTH_ENABLED", "false")

    import auth
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        auth.get_current_key(credentials=None, db=None)

    assert exc.value.status_code == 500
    assert "production" in exc.value.detail.lower()


def test_admin_key_is_read_dynamically(monkeypatch):
    import auth

    monkeypatch.setenv("COLONY_ADMIN_KEY", "first")
    from fastapi.security import HTTPAuthorizationCredentials

    first = HTTPAuthorizationCredentials(scheme="Bearer", credentials="first")
    auth.require_admin(credentials=first)

    monkeypatch.setenv("COLONY_ADMIN_KEY", "second")
    with pytest.raises(Exception):
        auth.require_admin(credentials=first)


def test_biometric_secret_fails_closed_in_production(monkeypatch):
    import aethel_interface

    monkeypatch.setenv("COLONY_ENV", "production")
    monkeypatch.delenv("COLONY_BAS_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        aethel_interface._load_bas_secret()
