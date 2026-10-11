"""CAIOS adapter and interop contract tests."""
import os
import sys
from pathlib import Path

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


def _make_class_api_checkout(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "CAIOS.txt").write_text("test system instructions", encoding="utf-8")
    (path / "orchestrator.py").write_text(
        """
import os
shared_memory = {
    "node_id": "test-node",
    "node_tier": 1,
    "tool_dispatcher": object(),
    "tool_addendum": "tools enabled",
    "last_cpol_result": {},
}
AD_AVAILABLE = True

class CAIOSOrchestrator:
    def __init__(self, node_id, node_tier=1, shared_memory=None):
        self.node_id = node_id
        self.node_tier = node_tier
        self.shared_memory = shared_memory or {}

    def handle_user_request(self, user_input, provider="openai"):
        if self.shared_memory.get("tool_dispatcher") is not None:
            raise RuntimeError("advisory adapter left tool dispatch enabled")
        if self.shared_memory.get("tool_addendum"):
            raise RuntimeError("advisory adapter left tool instructions enabled")
        if AD_AVAILABLE:
            raise RuntimeError("advisory adapter left self-extension enabled")
        if os.getenv("STRIPE_SECRET_KEY"):
            raise RuntimeError("payment secret leaked into advisory subprocess")
        self.shared_memory["last_cpol_result"] = {
            "status": "UNDECIDABLE",
            "logic": "test_only",
        }
        return "advisory response: " + user_input
""",
        encoding="utf-8",
    )


def test_caios_adapter_uses_class_entrypoint_and_is_advisory_only(tmp_path, monkeypatch):
    from caios_adapter import CAIOSAdapter, CAIOS_COMMIT

    source = tmp_path / "Project_Andrew"
    _make_class_api_checkout(source)
    adapter = CAIOSAdapter(source_path=str(source))
    # Unit-test fixture is a minimal fake checkout; pin verification itself is
    # covered by the mismatch test below and production uses the Git HEAD.
    monkeypatch.setattr(adapter, "_checkout_commit", lambda: CAIOS_COMMIT)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "must-not-enter-advisory-child")

    data = adapter.evaluate("review this proposal")
    assert data["status"] == "PASS"
    assert data["decision"] == "UNDECIDABLE"
    assert data["result"]["output"] == "advisory response: review this proposal"
    assert data["result"]["advisory_only"] is True
    assert data["evidence"]["tool_dispatch_enabled"] is False
    assert data["evidence"]["commit_matches_pin"] is True


def test_caios_adapter_rejects_unpinned_checkout(tmp_path, monkeypatch):
    from caios_adapter import CAIOSAdapter

    source = tmp_path / "Project_Andrew"
    _make_class_api_checkout(source)
    adapter = CAIOSAdapter(source_path=str(source))
    monkeypatch.setattr(adapter, "_checkout_commit", lambda: "f" * 40)

    data = adapter.evaluate("test prompt")
    assert data["status"] == "UNAVAILABLE"
    assert data["evidence"]["commit_matches_pin"] is False
    assert "pinned commit" in data["reasons"][0]


def test_caios_advisory_rejects_mutating_command_prompts():
    from caios_adapter import CAIOSAdapter

    data = CAIOSAdapter().evaluate("/design_agent security test")
    assert data["status"] == "FAIL"
    assert data["decision"] == "INVALID_INPUT"


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
