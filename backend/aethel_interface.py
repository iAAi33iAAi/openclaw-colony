"""
OpenClaw Colony — Aethel Interface
Python bridge to the Rust Aethel Safety Kernel (PyO3 native module).
Falls back to a pure-Python implementation when the compiled wheel is absent.

Gate 0 (Biometric) is evaluated HERE before passing to Gates 1-3.
Gate 0 requires a valid, unexpired, single-use biometric attestation token.

Architecture
------------
  Python coordinator  →  AethelInterface.validate()
                              ├── Gate 0: biometric.verify_attestation_token()  [Python/DB]
                              └── Gates 1-3: aethel_kernel.verify_safety_kernel()  [Rust PyO3]
                                            (falls back to _python_fallback() if wheel absent)
"""

from __future__ import annotations

import json
import logging
import os as _os
from typing import Optional

log = logging.getLogger("colony.aethel_interface")

# ── PyO3 native module import ─────────────────────────────────────────────────
# Try to import the compiled Rust kernel.  If the wheel has not been installed
# yet, we fall back to the pure-Python reference implementation and emit a
# warning so operators know to run `maturin build --release && pip install`.
try:
    import aethel_kernel as _rust_kernel  # type: ignore[import]
    _RUST_AVAILABLE = True
    log.info(
        "Aethel Rust kernel loaded (version %s). Gates 1-3 run natively.",
        getattr(_rust_kernel, "__version__", "unknown"),
    )
except ImportError:
    _rust_kernel = None  # type: ignore[assignment]
    _RUST_AVAILABLE = False
    log.warning(
        "aethel_kernel PyO3 module not found — using Python fallback for Gates 1-3. "
        "Run `cd backend/aethel-kernel && maturin build --release && "
        "pip install target/wheels/*.whl` to enable the native kernel."
    )

# ── Extraction signatures (Python fallback — kept in sync with Rust kernel) ───
# IMPORTANT: This list MUST mirror the patterns in lib.rs `extraction_patterns()`.
# When adding patterns to Rust, add the equivalent plain-text key here too.
_EXTRACTION_SIGNATURES = [
    "bypass_treasury",
    "extraction_vector",
    "multisig_bypass",
    "multisig bypass",
    "skip_gate",
    "skip gate",
    "shadow_balance",
    "shadow balance",
    "secondary_ledger",
    "secondary ledger",
    "hidden_transfer",
    "hidden transfer",
    "exfiltrate",
    "exfil",
    "covert_channel",
    "covert channel",
    "side_channel_transfer",
    "side channel transfer",
    "drain_pool",
    "drain pool",
    "rug_pull",
    "rug pull",
    "liquidity_drain",
    "liquidity drain",
    "vote_stuff",
    "vote stuff",
    "quorum_bypass",
    "quorum bypass",
    "consensus_override",
    "consensus override",
    "spoof_biometric",
    "spoof biometric",
    "replay_token",
    "replay token",
    "forge_attestation",
    "forge attestation",
]

LQ_THRESHOLD = 0.85

# ── BAS secret key ────────────────────────────────────────────────────────────
# Used to pass the HMAC secret into the Rust kernel for Gate 0 re-verification
# (the Rust kernel's Gate 0 is a lightweight HMAC-only check; the full 10-check
# Gate 0 is performed by biometric.verify_attestation_token() above).
#
# In production: set COLONY_BAS_SECRET to a stable value from your HSM/secrets
# manager.  If unset, a random secret is generated per-process — this means
# tokens signed in one process cannot be verified by another, and all tokens
# are invalidated on restart.  A startup warning is emitted when this occurs.
def _load_bas_secret() -> bytes:
    raw = _os.environ.get("COLONY_BAS_SECRET", "")
    if not raw:
        import secrets as _secrets
        ephemeral = _secrets.token_hex(32)
        log.warning(
            "COLONY_BAS_SECRET is not set. Using an ephemeral random secret. "
            "All biometric tokens will be invalidated on process restart and "
            "cannot be verified across multiple processes. "
            "Set COLONY_BAS_SECRET to a stable HSM-backed value in production."
        )
        return ephemeral.encode()
    return raw.encode()

_BAS_SECRET_BYTES: bytes = _load_bas_secret()


def _biometric_required() -> bool:
    """Read env var dynamically so patch.dict works correctly in tests."""
    return _os.environ.get("COLONY_BIOMETRIC_REQUIRED", "true").lower() == "true"

# Keep module-level alias for backward compatibility (reads at import time)
BIOMETRIC_REQUIRED = _biometric_required()


class AethelInterface:
    """
    Orchestrates the full 4-gate safety pipeline:

      Gate 0 — Biometric attestation (non-repudiation)
      Gate 1 — Sovereignty / human consent
      Gate 2 — Love Quality score ≥ 0.85
      Gate 3 — Extraction signature scan

    Calls the compiled Rust binary for Gates 1-3.
    Falls back to pure-Python if binary absent.
    """

    def validate(
        self,
        task_id: str,
        human_consent: bool,
        lq_score: float,
        agent_outputs: dict,
        biometric_token: Optional[dict] = None,
        action_type: str = "proposal",
        db=None,
    ) -> dict:
        """
        Full 4-gate validation.

        Args:
            task_id:          Unique task identifier
            human_consent:    Explicit consent flag (Gate 1)
            lq_score:         Love Quality composite (Gate 2)
            agent_outputs:    Dict of agent outputs (Gate 3 extraction scan)
            biometric_token:  Signed attestation token from BAS (Gate 0)
            action_type:      Action scope to verify against token
            db:               SQLAlchemy session (required when biometric enforced)

        Returns:
            {
              "verdict":          "APPROVED" | "BLOCKED",
              "blocked_at_gate":  None | 0 | 1 | 2 | 3,
              "reason":           None | str,
              "gates":            {gate_0: {...}, gate_1: {...}, ...},
              "actor":            {member_id, legal_name, ...} | None,
            }
        """
        gates: dict[str, dict] = {}

        # ── Gate 0: Biometric Attestation ────────────────────────────────────
        actor_info = None
        if _biometric_required():
            gate0_result = self._run_gate_0(
                biometric_token=biometric_token,
                action_type=action_type,
                db=db,
            )
            gates["gate_0"] = gate0_result
            if gate0_result["verdict"] == "FAIL":
                return self._blocked(0, gate0_result["reason"], gates)
            # Extract actor info for lineage binding
            if biometric_token:
                actor_info = {
                    "member_id":      biometric_token.get("member_id"),
                    "legal_name":     biometric_token.get("legal_name"),
                    "badge_serial":   biometric_token.get("badge_serial"),
                    "biometric_hash": biometric_token.get("biometric_hash"),
                    "location_node":  biometric_token.get("location_node"),
                    "scan_timestamp": biometric_token.get("issued_at"),
                    "duress":         biometric_token.get("duress_triggered", False),
                }
        else:
            gates["gate_0"] = {
                "verdict": "BYPASSED",
                "reason": "COLONY_BIOMETRIC_REQUIRED=false — development mode.",
            }

        # ── Gates 1-3: Aethel Kernel ─────────────────────────────────────────
        try:
            action_text = json.dumps(agent_outputs)
        except (TypeError, ValueError):
            action_text = "{}"

        if _RUST_AVAILABLE:
            kernel_result = self._call_pyo3_kernel(
                task_id=task_id,
                human_consent=human_consent,
                lq_score=lq_score,
                agent_outputs=agent_outputs,
                biometric_token=biometric_token,
            )
        else:
            kernel_result = self._python_fallback(human_consent, lq_score, action_text)

        # Merge gate results
        gates.update(kernel_result.get("gates", {}))

        result = {
            "verdict":         kernel_result["verdict"],
            "blocked_at_gate": kernel_result.get("blocked_at_gate"),
            "reason":          kernel_result.get("reason"),
            "gates":           gates,
            "actor":           actor_info,
        }
        return result

    # ── Gate 0 implementation ─────────────────────────────────────────────────

    def _run_gate_0(
        self,
        biometric_token: Optional[dict],
        action_type: str,
        db,
    ) -> dict:
        """
        Verify biometric attestation token.
        Returns {"verdict": "PASS"|"FAIL", "reason": str|None}
        """
        if db is None:
            return {
                "verdict": "FAIL",
                "reason": "GATE0_NO_DB: Database session required for biometric verification.",
            }

        try:
            from biometric import verify_attestation_token
            passed, reason = verify_attestation_token(
                db=db,
                token=biometric_token,
                required_action_type=action_type,
            )
            if passed:
                return {"verdict": "PASS", "reason": None}
            else:
                return {"verdict": "FAIL", "reason": reason}
        except Exception as exc:
            log.error("Gate 0 biometric check raised exception: %s", exc)
            return {
                "verdict": "FAIL",
                "reason": f"GATE0_ERROR: Biometric verification error — {exc}",
            }

    # ── Rust binary path ──────────────────────────────────────────────────────

    def _call_pyo3_kernel(
        self,
        task_id: str,
        human_consent: bool,
        lq_score: float,
        agent_outputs: dict,
        biometric_token: Optional[dict],
    ) -> dict:
        """
        Invoke the compiled Rust PyO3 kernel for Gates 1-3.

        Gate 0 (biometric) has already been verified by biometric.verify_attestation_token()
        before this method is called.  We construct a fresh valid HMAC bypass token so
        the Rust kernel's Gate 0 passes, then rely on the Python Gate 0 result already
        stored in `gates["gate_0"]` by the caller.

        The Rust kernel handles Gates 1 (consent), 2 (LQ threshold), and 3 (extraction
        signature scan) natively with constant-time HMAC and compiled regex patterns.
        """
        import aethel_kernel as _ak
        import hmac as _hmac_mod
        import hashlib as _hashlib
        import time as _time
        import math as _math

        # ── Type coercion: normalise inputs to the types PyO3 expects ─────────

        # task_id: must be a string; coerce None/int/etc. to str
        task_id_str: str = str(task_id) if task_id is not None else ""

        # human_consent: coerce any falsy value to False, truthy to True
        try:
            consent_bool: bool = bool(human_consent)
        except Exception:
            consent_bool = False

        # lq_score: must be a native int or float (not str, complex, list, etc.)
        # Non-numeric types are rejected with -1.0 so Rust Gate 2 blocks them.
        # We intentionally do NOT call float() on strings — "0.90" is not a
        # valid LQ score type and must be blocked at Gate 2.
        # bool is a subclass of int in Python: True==1.0, False==0.0.
        # Both are valid numeric types and should be treated as floats.
        if isinstance(lq_score, (bool, int, float)):
            lq_float: float = float(lq_score)
            if not _math.isfinite(lq_float):
                lq_float = float("nan")  # let Rust Gate 2 reject non-finite
        else:
            # str, complex, list, None, etc. → guaranteed Gate 2 block
            lq_float = -1.0

        # ── Serialise agent_outputs to a flat list of strings ─────────────────
        # We serialise the entire agent_outputs structure as a single JSON string
        # so that nested extraction signatures are still detected by Gate 3.
        try:
            full_json = json.dumps(agent_outputs)
        except (TypeError, ValueError):
            full_json = str(agent_outputs)
        outputs_list = [full_json]

        # ── Extract actor_id from biometric token ─────────────────────────────
        actor_id = ""
        if biometric_token and isinstance(biometric_token, dict):
            actor_id = biometric_token.get("member_id", "") or ""

        # ── Build a valid bypass HMAC token for the Rust kernel's Gate 0 ──────
        # Gate 0 was already fully verified by biometric.verify_attestation_token().
        # We mint a fresh short-lived token signed with _BAS_SECRET_BYTES so the
        # Rust kernel's HMAC-only Gate 0 passes without re-doing the full DB check.
        issued_at = int(_time.time())
        payload_json = json.dumps({"issued_at": issued_at, "member_id": actor_id or "bypass"})
        payload_hex = payload_json.encode().hex()
        sig = _hmac_mod.new(_BAS_SECRET_BYTES, payload_hex.encode(), _hashlib.sha256).hexdigest()
        bypass_token = f"{payload_hex}.{sig}"

        tx = _ak.TransactionPayload(
            task_id=task_id_str,
            token_hmac=bypass_token,
            human_consent=consent_bool,
            lq_score=lq_float,
            agent_outputs=outputs_list,
            previous_lineage_hash="GENESIS",
            actor_id=actor_id,
            action_type="proposal",
        )

        try:
            resp = _ak.verify_safety_kernel(tx, list(_BAS_SECRET_BYTES))
        except Exception as exc:
            log.error("PyO3 kernel call raised exception: %s — falling back to Python", exc)
            action_text = json.dumps(agent_outputs) if not isinstance(agent_outputs, str) else agent_outputs
            return self._python_fallback(human_consent, lq_score, action_text)

        # ── Convert GateResponse to the internal dict format ──────────────────
        if resp.approved:
            return {
                "verdict": "APPROVED",
                "blocked_at_gate": None,
                "reason": None,  # normalise: callers expect None on approval
                "gates": {
                    "gate_1": {"verdict": "PASS", "reason": None},
                    "gate_2": {"verdict": "PASS", "reason": None},
                    "gate_3": {"verdict": "PASS", "reason": None},
                },
            }
        else:
            gate_num = resp.failed_gate if resp.failed_gate is not None else 1
            gates: dict = {}
            for g in range(1, gate_num):
                gates[f"gate_{g}"] = {"verdict": "PASS", "reason": None}
            gates[f"gate_{gate_num}"] = {"verdict": "FAIL", "reason": resp.reason}
            for g in range(gate_num + 1, 4):
                gates[f"gate_{g}"] = {
                    "verdict": "NOT_REACHED",
                    "reason": f"Not reached — blocked at Gate {gate_num}",
                }
            return {
                "verdict": "BLOCKED",
                "blocked_at_gate": gate_num,
                "reason": resp.reason,
                "gates": gates,
            }

    # ── Pure-Python reference implementation ──────────────────────────────────

    def _python_fallback(
        self, human_consent: bool, lq_score: float, action_text: str
    ) -> dict:
        gates: dict[str, dict] = {}

        # Gate 1 — Sovereignty
        if not human_consent:
            gates["gate_1"] = {
                "verdict": "FAIL",
                "reason": "Gate 1 FAIL: No explicit human consent present.",
            }
            return self._blocked(1, gates["gate_1"]["reason"], gates)
        gates["gate_1"] = {"verdict": "PASS", "reason": None}

        # Gate 2 — Love Quality
        import math as _math
        _lq_invalid = (
            not isinstance(lq_score, (int, float))
            or _math.isnan(lq_score)
            or _math.isinf(lq_score)
            or lq_score < 0.0
            or lq_score > 1.0
        )
        if _lq_invalid or lq_score < LQ_THRESHOLD:
            if _lq_invalid:
                _reason = (
                    f"Gate 2 FAIL: LQ score '{lq_score}' is not a valid probability "
                    f"(must be a finite float in [0.0, 1.0])."
                )
            else:
                _reason = (
                    f"Gate 2 FAIL: LQ score {lq_score:.4f} below threshold {LQ_THRESHOLD}."
                )
            gates["gate_2"] = {"verdict": "FAIL", "reason": _reason}
            return self._blocked(2, gates["gate_2"]["reason"], gates)
        gates["gate_2"] = {"verdict": "PASS", "reason": None}

        # Gate 3 — Extraction scan
        lower = action_text.lower()
        found = [sig for sig in _EXTRACTION_SIGNATURES if sig in lower]
        if found:
            reason = f"Gate 3 FAIL: Extraction signatures detected: {found}."
            gates["gate_3"] = {"verdict": "FAIL", "reason": reason}
            return self._blocked(3, reason, gates)
        gates["gate_3"] = {"verdict": "PASS", "reason": None}

        return {
            "verdict": "APPROVED",
            "blocked_at_gate": None,
            "reason": None,
            "gates": gates,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _blocked(gate: int, reason: str, gates: dict) -> dict:
        # Fill remaining gates as not-reached
        for g in range(gate + 1, 4):
            gates.setdefault(
                f"gate_{g}",
                {"verdict": "NOT_REACHED", "reason": f"Not reached — blocked at Gate {gate}"},
            )
        return {
            "verdict": "BLOCKED",
            "blocked_at_gate": gate,
            "reason": reason,
            "gates": gates,
            "actor": None,
        }

