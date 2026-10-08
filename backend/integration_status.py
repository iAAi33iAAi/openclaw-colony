"""Runtime health and conformance probes for AETHEL integration boundaries.

The registry describes intended architecture. This module describes what is true
right now: configured, reachable, protocol-valid, degraded, or explicitly
blocked. Probes are read-only and never call /aethel/evaluate.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from aethel_interop import HttpInteropClient, InteropError, PROTOCOL
from caios_adapter import CAIOSAdapter


EXTERNAL_ENV = {
    "sports-math": "AETHEL_SPORTS_MATH_URL",
    "project-mono": "AETHEL_PROJECT_MONO_URL",
    "undermoon": "AETHEL_UNDERMOON_URL",
    "aethel-grid": "AETHEL_GRID_URL",
    "safety-kernel-proof": "AETHEL_PROOF_KERNEL_URL",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _semantic_status(payload: dict[str, Any]) -> str:
    value = str(payload.get("status", "")).strip().upper()
    if value in {"BLOCKED", "FAIL", "FAILED"}:
        return "BLOCKED"
    if value in {"DEGRADED", "WARN", "WARNING"}:
        return "DEGRADED"
    if value in {"OK", "HEALTHY", "PASS", "RUNNING", "CONNECTED"}:
        return "RUNNING"
    return "DEGRADED"


def _probe_external(key: str, endpoint: str) -> dict[str, Any]:
    checked_at = _now()
    try:
        client = HttpInteropClient(endpoint, timeout=3.0)
        health = client.health()
    except (InteropError, ValueError) as exc:
        return {
            "status": "UNREACHABLE",
            "checked_at": checked_at,
            "detail": str(exc),
        }

    protocol = health.get("protocol")
    health_state = _semantic_status(health)
    result: dict[str, Any] = {
        "status": health_state,
        "checked_at": checked_at,
        "protocol": protocol,
        "service": health.get("service"),
        "version": health.get("version"),
        "detail": "Health endpoint reachable.",
    }

    if protocol and protocol != PROTOCOL:
        result.update({
            "status": "DEGRADED",
            "detail": f"Unsupported protocol: {protocol}",
        })
        return result

    if health_state == "BLOCKED":
        result["detail"] = "Remote integration reports BLOCKED."
        return result

    try:
        capabilities = client.capabilities()
    except (InteropError, ValueError) as exc:
        result.update({
            "status": "DEGRADED",
            "detail": f"Health is reachable but capability negotiation failed: {exc}",
        })
        return result

    capability_protocol = capabilities.get("protocol")
    if capability_protocol and capability_protocol != PROTOCOL:
        result.update({
            "status": "DEGRADED",
            "detail": f"Capability protocol mismatch: {capability_protocol}",
        })
        return result

    result["capabilities"] = {
        "operations": capabilities.get("operations", []),
        "service": capabilities.get("service"),
        "version": capabilities.get("version"),
    }

    if health_state == "DEGRADED" or _semantic_status(capabilities) in {"DEGRADED", "BLOCKED"}:
        result["status"] = _semantic_status(capabilities)
        result["detail"] = "Endpoint is reachable but reports a degraded or blocked capability state."
    else:
        result["status"] = "RUNNING"
        result["detail"] = "Health and capability negotiation passed."

    return result


def _probe_caios() -> dict[str, Any]:
    state = CAIOSAdapter().status()
    return {
        "status": "RUNNING" if state["configured"] else "NOT_CONFIGURED",
        "checked_at": _now(),
        "protocol": PROTOCOL,
        "service": "caios",
        "version": "external",
        "detail": (
            "Pinned external checkout is configured for advisory use."
            if state["configured"]
            else "CAIOS_SOURCE_PATH is not configured or the checkout is incomplete."
        ),
        "advisory_only": True,
        "pinned_commit": state["pinned_commit"],
    }


def probe_integration(item: dict[str, Any]) -> dict[str, Any]:
    key = str(item["key"])
    endpoint_env = item.get("endpoint_env")

    if key == "caios":
        return _probe_caios()

    if not endpoint_env:
        return {
            "status": "RUNNING" if item.get("status") == "connected" else "NOT_CONFIGURED",
            "checked_at": _now(),
            "detail": "Implemented inside the current Colony process." if item.get("status") == "connected" else "No runtime endpoint is declared.",
            "local": True,
        }

    endpoint = os.getenv(str(endpoint_env), "").strip()
    if not endpoint:
        return {
            "status": "NOT_CONFIGURED",
            "checked_at": _now(),
            "detail": f"{endpoint_env} is not configured.",
        }

    return _probe_external(key, endpoint)


def runtime_integrations() -> list[dict[str, Any]]:
    from integration_registry import list_integrations

    items = list_integrations()
    probes: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(items)))) as pool:
        futures = {
            pool.submit(probe_integration, item): index
            for index, item in enumerate(items)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                probes[index] = future.result()
            except Exception as exc:
                probes[index] = {
                    "status": "ERROR",
                    "checked_at": _now(),
                    "detail": f"Runtime probe failed unexpectedly: {exc}",
                }

    output: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        probe = probes[index]
        enriched = {
            **item,
            "declared_status": item.get("status"),
            "runtime_status": probe["status"],
            "runtime_detail": probe.get("detail"),
            "last_checked_at": probe.get("checked_at"),
        }
        for key in ("protocol", "service", "version", "capabilities", "advisory_only", "pinned_commit"):
            if key in probe:
                enriched[key] = probe[key]
        output.append(enriched)
    return output
