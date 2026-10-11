"""CAIOS runtime adapter for advisory-only Colony integration.

The CAIOS checkout remains external and separately licensed. This adapter
requires the configured checkout to match the pinned upstream commit and runs
it as a separate process with a reduced environment. In advisory mode, model
tool dispatch and self-extension are disabled before the request is evaluated.

A subprocess is not a full OS sandbox; deployment isolation still requires
appropriate container/user/filesystem/network restrictions.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
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
MAX_PROMPT_CHARS = 80_000


_CHILD = r'''
import json
import re
import sys
from pathlib import Path

source = Path(sys.argv[1]).resolve()
prompt = sys.argv[2]
sys.path.insert(0, str(source))

try:
    # An advisory request is not allowed to invoke CAIOS command/update APIs.
    if prompt.lstrip().startswith("/"):
        raise ValueError("CAIOS advisory mode does not accept command-prefixed prompts")
    if re.search(r"(?<![\w])#UPDATE(?![\w])", prompt, re.IGNORECASE):
        raise ValueError("CAIOS advisory mode does not accept knowledge-update commands")

    import orchestrator as caios
    memory = getattr(caios, "shared_memory", {})
    if not isinstance(memory, dict):
        memory = {}

    # Keep the CAIOS reasoning pipeline, but disable action dispatch and
    # automatic specialist deployment for this advisory-only call.
    memory["tool_dispatcher"] = None
    memory["tool_addendum"] = ""
    memory["searcher"] = None
    if hasattr(caios, "AD_AVAILABLE"):
        caios.AD_AVAILABLE = False

    result = None
    module_entry = getattr(caios, "handle_user_request", None)
    if callable(module_entry):
        # Compatibility with any upstream version exposing a module function.
        result = module_entry(prompt)
    else:
        # The pinned Project Andrew version exposes this method on a class.
        orchestrator_class = getattr(caios, "CAIOSOrchestrator", None)
        if callable(orchestrator_class):
            try:
                node_id = str(memory.get("node_id") or "CAIOS_ADVISORY")
                try:
                    node_tier = int(memory.get("node_tier", 1))
                except (TypeError, ValueError):
                    node_tier = 1
                instance = orchestrator_class(
                    node_id=node_id,
                    node_tier=node_tier,
                    shared_memory=memory,
                )
                instance_entry = getattr(instance, "handle_user_request", None)
                if not callable(instance_entry):
                    raise RuntimeError("CAIOSOrchestrator.handle_user_request is unavailable")
                result = instance_entry(prompt)
            except Exception:
                # A module-level system_step is the fallback public request path.
                system_step = getattr(caios, "system_step", None)
                if not callable(system_step):
                    raise
                result = system_step(
                    user_input=prompt,
                    prompt_complexity="medium",
                    api_clients=memory.get("api_clients"),
                    user_id=memory.get("active_user"),
                )
        else:
            system_step = getattr(caios, "system_step", None)
            if not callable(system_step):
                raise RuntimeError("No compatible CAIOS public request entry point found")
            result = system_step(
                user_input=prompt,
                prompt_complexity="medium",
                api_clients=memory.get("api_clients"),
                user_id=memory.get("active_user"),
            )

    if isinstance(result, dict):
        output = result.get("llm_response") or result.get("output") or ""
        cpol = memory.get("last_cpol_result", {})
        if not isinstance(cpol, dict) or not cpol:
            cpol = result
    else:
        output = str(result) if result is not None else ""
        cpol = memory.get("last_cpol_result", {})

    print(json.dumps({
        "status": "ok",
        "output": output if isinstance(output, str) else str(output),
        "cpol": cpol if isinstance(cpol, dict) else {},
        "advisory_only": True,
        "tool_dispatch_enabled": False,
    }, default=str))
except Exception as exc:
    print(json.dumps({"status": "error", "error": str(exc)}))
'''


class CAIOSAdapter:
    def __init__(self, source_path: str | None = None, timeout: float = 30.0):
        configured = source_path or os.getenv("CAIOS_SOURCE_PATH", "")
        self.source_path = Path(configured).expanduser().resolve() if configured else None
        self.timeout = timeout

    def _has_required_files(self) -> bool:
        return bool(
            self.source_path
            and (self.source_path / "orchestrator.py").is_file()
            and (self.source_path / "CAIOS.txt").is_file()
        )

    def _checkout_commit(self) -> str | None:
        """Read the actual Git HEAD for the configured checkout; never trust metadata alone."""
        if not self.source_path:
            return None
        try:
            result = subprocess.run(
                ["git", "-C", str(self.source_path), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        commit = result.stdout.strip().lower()
        return commit if len(commit) == 40 and all(c in "0123456789abcdef" for c in commit) else None

    @property
    def configured(self) -> bool:
        return self._has_required_files() and self._checkout_commit() == CAIOS_COMMIT

    def status(self) -> dict[str, Any]:
        checkout_commit = self._checkout_commit()
        required_files = self._has_required_files()
        pin_matches = checkout_commit == CAIOS_COMMIT
        if not self.source_path:
            reason = "CAIOS_SOURCE_PATH is not configured."
        elif not required_files:
            reason = "CAIOS checkout is missing orchestrator.py or CAIOS.txt."
        elif not pin_matches:
            reason = "CAIOS checkout does not match the required pinned commit."
        else:
            reason = "Pinned CAIOS checkout verified."
        return {
            "service": "caios",
            "repository": CAIOS_REPOSITORY,
            "pinned_commit": CAIOS_COMMIT,
            "checkout_commit": checkout_commit,
            "commit_matches_pin": pin_matches,
            "configured": bool(required_files and pin_matches),
            "source_path": str(self.source_path) if self.source_path else None,
            "attribution_required": True,
            "advisory_only": True,
            "reason": reason,
        }

    def evaluate(self, prompt: str) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        state = self.status()
        prompt_is_invalid = (
            not isinstance(prompt, str)
            or not prompt.strip()
            or len(prompt) > MAX_PROMPT_CHARS
            or (isinstance(prompt, str) and prompt.lstrip().startswith("/"))
            or (
                isinstance(prompt, str)
                and re.search(r"(?<![\\w])#UPDATE(?![\\w])", prompt, re.IGNORECASE) is not None
            )
        )
        if prompt_is_invalid:
            return {
                "protocol": "aethel-interop/1",
                "service": "caios",
                "version": "external",
                "request_id": request_id,
                "status": "FAIL",
                "decision": "INVALID_INPUT",
                "reasons": [f"prompt must be a non-empty string no longer than {MAX_PROMPT_CHARS} characters."],
                "result": {},
                "evidence": state,
            }

        if not state["configured"]:
            return {
                "protocol": "aethel-interop/1",
                "service": "caios",
                "version": "external",
                "request_id": request_id,
                "status": "UNAVAILABLE",
                "decision": None,
                "reasons": [state["reason"]],
                "result": {},
                "evidence": state,
            }

        # Do not pass API keys or Colony secrets into a reasoning subprocess.
        # Local Ollama configuration may be supplied via OLLAMA_HOST.
        child_env = {}
        for name in (
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
            "HOME", "USERPROFILE", "LANG", "LC_ALL", "OLLAMA_HOST",
        ):
            value = os.environ.get(name)
            if value:
                child_env[name] = value
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONDONTWRITEBYTECODE"] = "1"

        try:
            proc = subprocess.run(
                [sys.executable, "-c", textwrap.dedent(_CHILD), str(self.source_path), prompt],
                cwd=str(self.source_path),
                env=child_env,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "protocol": "aethel-interop/1",
                "service": "caios",
                "version": "external",
                "request_id": request_id,
                "status": "ERROR",
                "decision": None,
                "reasons": ["CAIOS advisory request timed out."],
                "result": {},
                "evidence": state,
            }
        except OSError as exc:
            return {
                "protocol": "aethel-interop/1",
                "service": "caios",
                "version": "external",
                "request_id": request_id,
                "status": "ERROR",
                "decision": None,
                "reasons": [f"Unable to launch CAIOS advisory process: {exc}"],
                "result": {},
                "evidence": state,
            }

        stdout = proc.stdout.strip().splitlines()
        payload: dict[str, Any] = {}
        if stdout:
            try:
                parsed = json.loads(stdout[-1])
                if isinstance(parsed, dict):
                    payload = parsed
            except json.JSONDecodeError:
                payload = {}

        if proc.returncode != 0 or payload.get("status") != "ok":
            reason = payload.get("error") or proc.stderr.strip() or f"CAIOS exited {proc.returncode}"
            return {
                "protocol": "aethel-interop/1",
                "service": "caios",
                "version": "external",
                "request_id": request_id,
                "status": "ERROR",
                "decision": None,
                "reasons": [str(reason)],
                "result": {},
                "evidence": {
                    **state,
                    "child_exit_code": proc.returncode,
                    "stderr_hash": hashlib.sha256(proc.stderr.encode()).hexdigest(),
                },
            }

        cpol = payload.get("cpol", {})
        return {
            "protocol": "aethel-interop/1",
            "service": "caios",
            "version": "external",
            "request_id": request_id,
            "status": "PASS",
            "decision": cpol.get("status") if isinstance(cpol, dict) else None,
            "reasons": [],
            "result": {
                "output": payload.get("output", ""),
                "cpol": cpol if isinstance(cpol, dict) else {},
                "advisory_only": True,
            },
            "evidence": {
                **state,
                "child_exit_code": proc.returncode,
                "stdout_hash": hashlib.sha256(proc.stdout.encode()).hexdigest(),
                "tool_dispatch_enabled": payload.get("tool_dispatch_enabled", True),
            },
        }
