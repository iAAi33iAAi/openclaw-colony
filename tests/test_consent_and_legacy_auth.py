"""Tests for explicit consent defaults and authentication on the legacy API."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
ORCHESTRATOR = BACKEND / "colony-agents" / "orchestrator"
for item in (str(BACKEND), str(BACKEND / "colony-agents"), str(ORCHESTRATOR)):
    if item not in sys.path:
        sys.path.insert(0, item)


def _load_legacy_coordinator():
    """Import the legacy route module with agent implementations stubbed."""
    names = [
        "love_quality",
        "love_quality.love_quality_engine",
        "aethel_interface",
        "colony_agents",
        "colony_agents.strategic_agent",
        "colony_agents.technical_agent",
        "colony_agents.resources_agent",
        "colony_agents.comms_agent",
        "colony_agents.analysis_agent",
        "colony_agents.quality_agent",
        "colony_agents.innovation_agent",
    ]
    missing = object()
    saved = {name: sys.modules.get(name, missing) for name in names}
    for name in names:
        sys.modules[name] = MagicMock()
    sys.modules.pop("colony_coordinator", None)
    try:
        return importlib.import_module("colony_coordinator")
    finally:
        for name, original in saved.items():
            if original is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def test_legacy_consent_defaults_to_false_and_is_strict():
    legacy = _load_legacy_coordinator()
    assert legacy.TaskRequest(prompt="consent omitted").human_consent is False
    assert legacy.ColonyTask(prompt="consent omitted").human_consent is False
    with pytest.raises(ValidationError):
        legacy.TaskRequest(prompt="not a boolean", human_consent="false")


def test_legacy_process_route_declares_bearer_authentication():
    legacy = _load_legacy_coordinator()
    operation = legacy.app.openapi()["paths"]["/process"]["post"]
    assert operation.get("security"), "legacy /process route must advertise API-key security"


def test_missing_bearer_credentials_are_rejected(monkeypatch):
    monkeypatch.setenv("COLONY_AUTH_ENABLED", "true")
    from auth import get_current_key

    with pytest.raises(HTTPException) as exc:
        get_current_key(credentials=None)
    assert exc.value.status_code == 401
