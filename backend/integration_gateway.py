"""AETHEL external integration gateway.

All external engines are advisory/dry-run services. A service response is
evidence for the Colony and never bypasses the local Rust/PyO3 safety gates.
"""
from __future__ import annotations

import os
from typing import Any

from aethel_interop import HttpInteropClient, InteropError
from caios_adapter import CAIOSAdapter


EXTERNALS = {
    "sports-math": "AETHEL_SPORTS_MATH_URL",
    "project-mono": "AETHEL_PROJECT_MONO_URL",
    "undermoon": "AETHEL_UNDERMOON_URL",
    "aethel-grid": "AETHEL_GRID_URL",
    "safety-kernel-proof": "AETHEL_PROOF_KERNEL_URL",
}


def _client(key: str) -> HttpInteropClient:
    env_name = EXTERNALS.get(key)
    if not env_name:
        raise KeyError(f"unknown external integration: {key}")
    url = os.getenv(env_name, "").strip()
    if not url:
        raise InteropError(f"{env_name} is not configured")
    return HttpInteropClient(url)


def health(key: str) -> dict[str, Any]:
    if key == "caios":
        return CAIOSAdapter().status()
    return _client(key).health()


def capabilities(key: str) -> dict[str, Any]:
    if key == "caios":
        return CAIOSAdapter().status()
    return _client(key).capabilities()


def evaluate(
    key: str,
    *,
    request_id: str,
    operation: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if key == "caios":
        if operation != "reasoning":
            raise InteropError("CAIOS supports only the reasoning adapter operation")
        return CAIOSAdapter().evaluate(str(payload.get("prompt", "")))

    return _client(key).evaluate(
        request_id=request_id,
        operation=operation,
        payload=payload,
    ).__dict__
