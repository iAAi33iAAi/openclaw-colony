"""CAIOS adapter and interop contract tests."""
import os
import sys

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def test_caios_adapter_reports_unconfigured_without_source_path(monkeypatch):
    monkeypatch.delenv("CAIOS_SOURCE_PATH", raising=False)
    from caios_adapter import CAIOSAdapter
    data = CAIOSAdapter().evaluate("test prompt")
    assert data["protocol"] == "aethel-interop/1"
    assert data["service"] == "caios"
    assert data["status"] == "UNAVAILABLE"


def test_interop_response_validates_protocol():
    from aethel_interop import InteropError, InteropResponse

    good = {
        "protocol": "aethel-interop/1",
        "service": "sports-math",
        "version": "0.1",
        "request_id": "r1",
        "status": "PASS",
        "decision": "OK",
        "reasons": [],
        "result": {},
        "evidence": {},
    }
    assert InteropResponse.from_json(good).service == "sports-math"

    bad = dict(good, protocol="wrong/1")
    try:
        InteropResponse.from_json(bad)
    except InteropError:
        pass
    else:
        raise AssertionError("protocol mismatch must be rejected")
