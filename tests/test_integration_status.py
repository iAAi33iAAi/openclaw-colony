"""Runtime integration status tests."""

import os
import sys

import pytest

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
for path in [BACKEND, os.path.join(BACKEND, "colony-agents"), os.path.join(BACKEND, "love-quality")]:
    if path not in sys.path:
        sys.path.insert(0, path)


class FakeInteropClient:
    def __init__(self, base_url: str, *, timeout: float = 8.0):
        self.base_url = base_url
        self.timeout = timeout

    def health(self):
        return {
            "protocol": "aethel-interop/1",
            "service": "fake",
            "version": "1.2.3",
            "status": "OK",
        }

    def capabilities(self):
        return {
            "protocol": "aethel-interop/1",
            "service": "fake",
            "version": "1.2.3",
            "status": "OK",
            "operations": ["evaluate"],
        }


class BlockedInteropClient(FakeInteropClient):
    def health(self):
        payload = super().health()
        payload["status"] = "BLOCKED"
        return payload


class BrokenInteropClient(FakeInteropClient):
    def health(self):
        raise RuntimeError("unreachable")


@pytest.mark.parametrize(
    "client,expected",
    [
        (FakeInteropClient, "RUNNING"),
        (BlockedInteropClient, "BLOCKED"),
    ],
)
def test_external_probe_states(monkeypatch, client, expected):
    import integration_status

    monkeypatch.setattr(integration_status, "HttpInteropClient", client)
    item = {
        "key": "project-mono",
        "status": "planned",
        "endpoint_env": "AETHEL_PROJECT_MONO_URL",
    }
    monkeypatch.setenv("AETHEL_PROJECT_MONO_URL", "http://example.invalid")
    result = integration_status.probe_integration(item)
    assert result["status"] == expected
    assert result["protocol"] == "aethel-interop/1"


def test_external_probe_marks_unconfigured_without_network(monkeypatch):
    import integration_status

    monkeypatch.delenv("AETHEL_PROJECT_MONO_URL", raising=False)
    item = {
        "key": "project-mono",
        "status": "planned",
        "endpoint_env": "AETHEL_PROJECT_MONO_URL",
    }
    result = integration_status.probe_integration(item)
    assert result["status"] == "NOT_CONFIGURED"


def test_external_probe_marks_unreachable(monkeypatch):
    import integration_status

    class RaisingClient:
        def __init__(self, *args, **kwargs):
            pass

        def health(self):
            from integration_status import InteropError
            raise InteropError("connection refused")

    monkeypatch.setattr(integration_status, "HttpInteropClient", RaisingClient)
    monkeypatch.setenv("AETHEL_PROJECT_MONO_URL", "http://example.invalid")
    item = {
        "key": "project-mono",
        "status": "planned",
        "endpoint_env": "AETHEL_PROJECT_MONO_URL",
    }
    result = integration_status.probe_integration(item)
    assert result["status"] == "UNREACHABLE"


def test_local_in_process_integration_is_running():
    import integration_status

    item = {"key": "colony-core", "status": "connected", "endpoint_env": None}
    result = integration_status.probe_integration(item)
    assert result["status"] == "RUNNING"
    assert result["local"] is True
