"""CAIOS runtime adapter.

This adapter intentionally does not vendor or copy the CAIOS source tree.
Set CAIOS_SOURCE_PATH to a local checkout of ELXaber/chaos-persona. The adapter
imports Project_Andrew/orchestrator.py in a child process, captures its final
public result, and turns it into AETHEL Interop v1 evidence.

CAIOS is an independently licensed GPL-3.0 project; keep its LICENSE.txt and
required attribution with the external checkout/deployment.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path
from typing import Any


CAIOS_REPOSITORY = "ELXaber/chaos-persona"
CAIOS_COMMIT = "cabe1d0b77c5080f86f49cc2a7c230785e0ceb8e"
CAIOS_ATTRIBUTION = (
    "Built on CAIOS v1.0 by inventor Jonathan M. Schack – "
    "Patent Pending US 19/433,771 & 19/390,493 – www.cai-os.com"
)


_CHILD = r'''
import json
import sys
from pathlib import Path

source = Path(sys.argv[1]).resolve()
prompt = sys.argv[2]
sys.path.insert(0, str(source))

try:
    import orchestrator
    fn = getattr(orchestrator, "handle_user_request", None)
    if fn is None:
        raise RuntimeError("CAIOS orchestrator.handle_user_request is unavailable")
    result = fn(prompt)
    memory = getattr(orchestrator, "shared_memory", {})
    cpol = memory.get("last_cpol_result", {})
    print(json.dumps({
        "status": "ok",
        "output": result if isinstance(result, str) else str(result),
        "cpol": cpol if isinstance(cpol, dict) else {},
    }, default=str))
except Exception as exc:
    print(json.dumps({"status": "error", "error": str(exc)}))
'''


class CAIOSAdapter:
    def __init__(self, source_path: str | None = None, timeout: float = 30.0):
        configured = source_path or os.getenv("CAIOS_SOURCE_PATH", "")
        self.source_path = Path(configured).expanduser().resolve() if configured else None
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(
            self.source_path
            and (self.source_path / "orchestrator.py").is_file()
            and (self.source_path / "CAIOS.txt").is_file()
        )

    def status(self) -> dict[str, Any]:
        return {
            "service": "caios",
            "repository": CAIOS_REPOSITORY,
            "pinned_commit": CAIOS_COMMIT,
            "configured": self.configured,
            "source_path": str(self.source_path) if self.source_path else None,
            "attribution_required": True,
        }

    def evaluate(self, prompt: str) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        if not self.configured:
            return {
                "protocol": "aethel-interop/1",
                "service": "caios",
                "version": "external",
                "request_id": request_id,
                "status": "UNAVAILABLE",
                "decision": None,
                "reasons": ["CAIOS_SOURCE_PATH is not configured or the checkout is incomplete."],
                "result": {},
                "evidence": self.status(),
            }

        proc = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(_CHILD), str(self.source_path), prompt],
            text=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )

        stdout = proc.stdout.strip().splitlines()
        payload: dict[str, Any] = {}
        if stdout:
            try:
                payload = json.loads(stdout[-1])
            except json.JSONDecodeError:
                payload = {}

        if proc.returncode != 0 or payload.get("status") != "ok":
            return {
                "protocol": "aethel-interop/1",
                "service": "caios",
                "version": "external",
                "request_id": request_id,
                "status": "ERROR",
                "decision": None,
                "reasons": [payload.get("error", proc.stderr.strip() or f"CAIOS exited {proc.returncode}")],
                "result": {},
                "evidence": {
                    **self.status(),
                    "stderr_hash": __import__("hashlib").sha256(proc.stderr.encode()).hexdigest(),
                },
            }

        cpol = payload.get("cpol", {})
        return {
            "protocol": "aethel-interop/1",
            "service": "caios",
            "version": "external",
            "request_id": request_id,
            "status": "PASS",
            "decision": cpol.get("status"),
            "reasons": [],
            "result": {
                "output": payload.get("output", ""),
                "cpol": cpol,
            },
            "evidence": {
                **self.status(),
                "child_exit_code": proc.returncode,
                "stdout_hash": __import__("hashlib").sha256(proc.stdout.encode()).hexdigest(),
            },
        }
