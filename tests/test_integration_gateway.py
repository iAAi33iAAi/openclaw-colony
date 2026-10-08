import os
import sys

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def test_gateway_rejects_unconfigured_external():
    from integration_gateway import health
    try:
        health("sports-math")
    except Exception as exc:
        assert "AETHEL_SPORTS_MATH_URL" in str(exc)
    else:
        raise AssertionError("unconfigured service must not appear healthy")


def test_gateway_caios_is_local_status(monkeypatch):
    monkeypatch.delenv("CAIOS_SOURCE_PATH", raising=False)
    from integration_gateway import health
    data = health("caios")
    assert data["service"] == "caios"
    assert data["configured"] is False
