"""Production-mode guardrail tests."""

import os
import sys

import pytest

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def test_production_rejects_stripe_mock_mode(monkeypatch):
    import stripe_bridge

    monkeypatch.setenv("COLONY_ENV", "production")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError):
        stripe_bridge.validate_payment_mode()


def test_development_allows_mock_payment_mode(monkeypatch):
    import stripe_bridge

    monkeypatch.setenv("COLONY_ENV", "development")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)

    stripe_bridge.validate_payment_mode()
