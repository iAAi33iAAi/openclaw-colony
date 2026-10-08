"""AETHEL Interop v1 — small, dependency-free service boundary.

The platform treats every external engine as an independent process/service.
Responses are JSON, versioned, bounded, and never allowed to authorize an
action by themselves. The Colony safety kernel remains the final execution gate.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


PROTOCOL = "aethel-interop/1"


class InteropError(RuntimeError):
    """Raised when an external integration cannot be reached or understood."""


@dataclass(frozen=True)
class InteropResponse:
    protocol: str
    service: str
    version: str
    request_id: str
    status: str
    decision: str | None
    reasons: list[str]
    result: dict[str, Any]
    evidence: dict[str, Any]

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "InteropResponse":
        if payload.get("protocol") != PROTOCOL:
            raise InteropError("unsupported interop protocol")
        required = ("service", "version", "request_id", "status", "reasons", "result", "evidence")
        missing = [key for key in required if key not in payload]
        if missing:
            raise InteropError(f"interop response missing fields: {missing}")
        return cls(
            protocol=payload["protocol"],
            service=str(payload["service"]),
            version=str(payload["version"]),
            request_id=str(payload["request_id"]),
            status=str(payload["status"]),
            decision=payload.get("decision"),
            reasons=[str(x) for x in payload.get("reasons", [])],
            result=dict(payload.get("result", {})),
            evidence=dict(payload.get("evidence", {})),
        )


class HttpInteropClient:
    """HTTP client for AETHEL Interop v1 services.

    Only explicit service URLs are used. Timeouts are short by default and the
    client never retries mutating operations.
    """

    def __init__(self, base_url: str, *, timeout: float = 8.0):
        base_url = base_url.strip().rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("interop endpoint must use http:// or https://")
        self.base_url = base_url
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise InteropError(f"interop request failed: {exc}") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InteropError("interop service returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise InteropError("interop service returned a non-object JSON value")
        return data

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/aethel/health")

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/aethel/capabilities")

    def evaluate(self, *, request_id: str, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None) -> InteropResponse:
        data = self._request(
            "POST",
            "/aethel/evaluate",
            {
                "protocol": PROTOCOL,
                "request_id": request_id,
                "operation": operation,
                "payload": payload,
                "context": context or {},
                "dry_run": True,
            },
        )
        return InteropResponse.from_json(data)


def make_unavailable(service: str, request_id: str, reason: str) -> InteropResponse:
    return InteropResponse(
        protocol=PROTOCOL,
        service=service,
        version="unknown",
        request_id=request_id,
        status="UNAVAILABLE",
        decision=None,
        reasons=[reason],
        result={},
        evidence={"timestamp": time.time()},
    )
