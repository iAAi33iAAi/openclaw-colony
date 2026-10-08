"""AETHEL platform integration registry.

This registry deliberately distinguishes code that is already inside the running
Colony service from repositories that still require a separate service/API
connection. It prevents documentation from pretending that every repository is
already runtime-wired into one process.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class Integration:
    key: str
    name: str
    repository: str
    role: str
    status: str
    connection: str
    endpoint_env: Optional[str] = None

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.endpoint_env:
            configured = bool(os.getenv(self.endpoint_env, "").strip())
            data["configured"] = configured
            if configured:
                data["endpoint"] = os.getenv(self.endpoint_env)
        else:
            data["configured"] = self.status == "connected"
        return data


INTEGRATIONS = (
    Integration(
        "colony-core",
        "OpenClaw Colony",
        "iAAi33iAAi/openclaw-colony",
        "Primary application, API, database, federation, payments",
        "connected",
        "In-process",
    ),
    Integration(
        "safety-kernel",
        "AETHEL Safety Kernel",
        "iAAi33iAAi/safety-kernel",
        "Execution evidence and verification",
        "connected",
        "Rust/PyO3 module inside Colony",
    ),
    Integration(
        "agent-orchestration",
        "Seven-Agent Orchestration",
        "iAAi33iAAi/openclaw-colony",
        "Runs the current seven specialist agents",
        "connected",
        "In-process",
    ),
    Integration(
        "sports-math",
        "Sports Math / Allocation Engine",
        "iAAi33iAAi/sports-math-agent-orchestration",
        "Resource allocation and mathematical routing",
        "planned",
        "Service/API adapter not yet configured",
        "AETHEL_SPORTS_MATH_URL",
    ),
    Integration(
        "project-mono",
        "Project Mono",
        "iAAi33iAAi/project-mono",
        "Change approval and evidence gate",
        "planned",
        "Service/API adapter not yet configured",
        "AETHEL_PROJECT_MONO_URL",
    ),
    Integration(
        "undermoon",
        "Undermoon",
        "iAAi33iAAi/undermoon",
        "Protocol rules and cross-language conformance",
        "planned",
        "Conformance service/API not yet configured",
        "AETHEL_UNDERMOON_URL",
    ),
    Integration(
        "safety-kernel-proof",
        "AETHEL Safety Kernel Proof Service",
        "iAAi33iAAi/safety-kernel",
        "Read-only tamper-evidence and proof verification",
        "optional",
        "External AETHEL Interop endpoint via AETHEL_PROOF_KERNEL_URL",
    ),
    Integration(
        "caios",
        "CAIOS / Project Andrew",
        "ELXaber/chaos-persona",
        "External paradox/entropy reasoning runtime (advisory only)",
        "optional",
        "Separate GPL-3.0 checkout via CAIOS_SOURCE_PATH",
    ),
    Integration(
        "aethel-grid",
        "AETHEL Grid",
        "iAAi33iAAi/aethel-grid",
        "Canonical grid architecture and future physical systems",
        "planned",
        "Grid service/physical adapter not yet configured",
        "AETHEL_GRID_URL",
    ),
)


def list_integrations() -> list[dict]:
    return [item.to_dict() for item in INTEGRATIONS]


def local_capabilities() -> dict[str, bool]:
    """Report whether the current process can import the key local modules."""
    modules = {
        "aethel_interface": "aethel_interface",
        "aethel_kernel": "aethel_kernel",
        "agent_orchestrator": "colony_agents.orchestrator.colony_coordinator_v2",
        "stripe_bridge": "stripe_bridge",
        "federation": "federation",
        "caios_adapter": "caios_adapter",
    }
    return {
        key: importlib.util.find_spec(module) is not None
        for key, module in modules.items()
    }
