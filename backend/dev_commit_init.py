"""
OpenClaw Colony — DEV_COMMIT_INIT
==================================
The Genesis startup sequence. Transforms a cold node into a live,
sovereign, deterministic system in one atomic operation.

Sequence:
  1. validate_secrets()         — check all required env vars
  2. create_genesis_block()     — build the GENESIS lineage record
  3. init_node_state_machine()  — wire NodeStateMachine singleton
  4. commit_genesis()           — write GENESIS to SQLite lineage chain
  5. sm.transition(STANDALONE)  — node is now formally initialised
  6. Return status dict         — {"status": "Genesis_Committed", "tip": 0, ...}

This module is idempotent:
  - If a GENESIS record already exists, it is detected and skipped.
  - The state machine is re-initialised to match the existing chain tip.
  - Safe to call on every server restart.

Environment variables required:
  COLONY_NODE_ID       — unique node name (e.g. "node-001-bethel")
  COLONY_NODE_URL      — public base URL (e.g. "https://node001.openclaw.net")
  COLONY_BAS_SECRET    — HMAC key for biometric tokens (CRITICAL in production)
  COLONY_ADMIN_KEY     — Bearer token for federation calls

Optional:
  COLONY_PEERS         — comma-separated peer URLs
  COLONY_DB_PATH       — SQLite path (default: colony.db)
  COLONY_DEV_MODE      — if "true", relaxes secret validation for local dev
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("colony.init")

# Top-level imports so tests can patch dev_commit_init.<name>
try:
    from federation import init_federation_tables
except Exception:
    init_federation_tables = None  # type: ignore[assignment]

try:
    from biometric import init_biometric_tables
except Exception:
    init_biometric_tables = None  # type: ignore[assignment]

try:
    from db import LineageRecord, SessionLocal, Base, engine
except Exception:
    LineageRecord = SessionLocal = Base = engine = None  # type: ignore[assignment]

try:
    from state_machine import (
        init_node_state_machine,
        get_node_state_machine,
        NodeState,
    )
except Exception:
    init_node_state_machine = get_node_state_machine = NodeState = None  # type: ignore[assignment]

# ── Environment ───────────────────────────────────────────────────────────────
NODE_ID    = os.environ.get("COLONY_NODE_ID",   "node-001-bethel")
NODE_URL   = os.environ.get("COLONY_NODE_URL",  "http://localhost:8000")
ADMIN_KEY  = os.environ.get("COLONY_ADMIN_KEY", "")
BAS_SECRET = os.environ.get("COLONY_BAS_SECRET", "")
PEERS_RAW  = os.environ.get("COLONY_PEERS", "")
DEV_MODE   = os.environ.get("COLONY_DEV_MODE", "false").lower() == "true"

PEER_URLS: list[str] = [p.strip() for p in PEERS_RAW.split(",") if p.strip()]

# ── GENESIS constants ─────────────────────────────────────────────────────────
GENESIS_TASK_ID     = "GENESIS"
GENESIS_PREV_HASH   = "0" * 64          # 64 zeros — the primordial anchor
GENESIS_DESCRIPTION = (
    "OpenClaw Colony Genesis Block — "
    "Sovereign node initialised. Laminar Flow begins."
)


# ══════════════════════════════════════════════════════════════════════════════
# Step 1: Secret Validation
# ══════════════════════════════════════════════════════════════════════════════

class SecretValidationError(RuntimeError):
    """Raised when a required secret is missing or insecure."""
    pass


def validate_secrets(strict: bool = not DEV_MODE) -> dict:
    """
    Validate all required environment variables.

    Reads directly from os.environ at call time (not module-level globals)
    so that patch.dict(os.environ) works correctly in tests.

    In strict mode (production): raises SecretValidationError if any
    critical secret is missing or uses a known-insecure default.

    In dev mode: emits warnings but does not raise.

    Returns a dict of validation results for logging.
    """
    # Read live from os.environ so tests can patch correctly
    bas_secret = os.environ.get("COLONY_BAS_SECRET", "")
    admin_key  = os.environ.get("COLONY_ADMIN_KEY", "")
    node_id    = os.environ.get("COLONY_NODE_ID", "node-001-bethel")
    node_url   = os.environ.get("COLONY_NODE_URL", "http://localhost:8000")
    peers_raw  = os.environ.get("COLONY_PEERS", "")
    peer_count = len([p for p in peers_raw.split(",") if p.strip()])

    results = {}
    warnings = []
    errors   = []

    # COLONY_BAS_SECRET
    if not bas_secret:
        msg = (
            "COLONY_BAS_SECRET is not set. "
            "An ephemeral random key will be used — all tokens invalidated on restart. "
            "Set COLONY_BAS_SECRET to a stable HSM-backed value in production."
        )
        warnings.append(msg)
        results["COLONY_BAS_SECRET"] = "MISSING — ephemeral key in use"
        if strict:
            errors.append("COLONY_BAS_SECRET")
    elif len(bas_secret) < 32:
        msg = "COLONY_BAS_SECRET is set but shorter than 32 characters — use a longer secret."
        warnings.append(msg)
        results["COLONY_BAS_SECRET"] = "WEAK — too short"
        if strict:
            errors.append("COLONY_BAS_SECRET (too short)")
    else:
        results["COLONY_BAS_SECRET"] = "OK"

    # COLONY_ADMIN_KEY
    if not admin_key:
        msg = (
            "COLONY_ADMIN_KEY is not set. "
            "Federation endpoints will reject all peer requests. "
            "Set COLONY_ADMIN_KEY to a stable shared secret."
        )
        warnings.append(msg)
        results["COLONY_ADMIN_KEY"] = "MISSING"
        if strict:
            errors.append("COLONY_ADMIN_KEY")
    else:
        results["COLONY_ADMIN_KEY"] = "OK"

    # COLONY_NODE_ID
    if node_id == "node-001-bethel":
        results["COLONY_NODE_ID"] = f"DEFAULT ({node_id}) — consider a unique name"
    else:
        results["COLONY_NODE_ID"] = f"OK ({node_id})"

    # COLONY_NODE_URL
    if node_url.startswith("http://localhost"):
        results["COLONY_NODE_URL"] = f"LOCAL ({node_url}) — set public URL for federation"
    else:
        results["COLONY_NODE_URL"] = f"OK ({node_url})"

    # Peers
    results["COLONY_PEERS"] = f"{peer_count} peer(s) configured"

    # Log all warnings
    for w in warnings:
        log.warning("[INIT] ⚠️  %s", w)

    # In strict mode, raise on any error
    if errors and strict:
        raise SecretValidationError(
            f"[INIT] FATAL: Required secrets missing or insecure: {errors}. "
            f"Set them via environment variables or use COLONY_DEV_MODE=true for local development."
        )

    log.info("[INIT] Secret validation complete: %s", results)
    return results


# ══════════════════════════════════════════════════════════════════════════════
# Step 2: Genesis Block Creation
# ══════════════════════════════════════════════════════════════════════════════

def _compute_genesis_hash(node_id: str, timestamp: str) -> str:
    """
    Compute the GENESIS lineage hash.

    Hash input: SHA-256(GENESIS_PREV_HASH || node_id || timestamp || description)
    Length-prefixed to prevent concatenation collisions (matches Rust kernel).
    """
    import hashlib as _hl
    h = _hl.sha256()

    def _write(s: str):
        b = s.encode()
        h.update(len(b).to_bytes(4, "big"))
        h.update(b)

    _write(GENESIS_PREV_HASH)
    _write(node_id)
    _write(GENESIS_TASK_ID)
    _write("GENESIS_INIT")
    _write(timestamp)
    _write(GENESIS_DESCRIPTION)
    return h.hexdigest()


def create_genesis_block(node_id: str) -> dict:
    """
    Build the GENESIS lineage record dict.

    Returns a dict ready to be written to the LineageRecord table.
    Does NOT write to DB — that is done by commit_genesis().
    """
    now = datetime.now(timezone.utc)
    ts  = now.isoformat()

    genesis_hash = _compute_genesis_hash(node_id, ts)

    # Prompt hash = SHA-256 of the genesis description
    prompt_hash = hashlib.sha256(GENESIS_DESCRIPTION.encode()).hexdigest()

    block = {
        "task_id":      GENESIS_TASK_ID,
        "prompt_hash":  prompt_hash,
        "lq_composite": 1.0,            # Genesis is unconditionally sovereign
        "lineage_hash": genesis_hash,
        "prev_hash":    GENESIS_PREV_HASH,
        "committed_at": now,
        "node_id":      node_id,
        "description":  GENESIS_DESCRIPTION,
    }

    log.info(
        "[INIT] Genesis block created: hash=%s... node=%s ts=%s",
        genesis_hash[:16], node_id, ts
    )
    return block


# ══════════════════════════════════════════════════════════════════════════════
# Step 4: Commit Genesis to SQLite Lineage Chain
# ══════════════════════════════════════════════════════════════════════════════

def commit_genesis(genesis_block: dict, db) -> tuple[bool, str]:
    """
    Write the GENESIS block to the SQLite lineage chain.

    Idempotent: if a GENESIS record already exists, returns
    (False, existing_hash) without writing a duplicate.

    Returns:
        (True,  genesis_hash)  — freshly committed
        (False, existing_hash) — already existed, skipped
    """
    existing = db.query(LineageRecord).filter_by(task_id=GENESIS_TASK_ID).first()
    if existing:
        log.info(
            "[INIT] GENESIS already committed (hash=%s...). Skipping.",
            existing.lineage_hash[:16]
        )
        return False, existing.lineage_hash

    record = LineageRecord(
        task_id      = genesis_block["task_id"],
        prompt_hash  = genesis_block["prompt_hash"],
        lq_composite = genesis_block["lq_composite"],
        lineage_hash = genesis_block["lineage_hash"],
        prev_hash    = genesis_block["prev_hash"],
        committed_at = genesis_block["committed_at"],
    )
    db.add(record)
    db.commit()

    log.info(
        "[INIT] ✅ GENESIS committed to lineage chain: hash=%s...",
        genesis_block["lineage_hash"][:16]
    )
    return True, genesis_block["lineage_hash"]


# ══════════════════════════════════════════════════════════════════════════════
# Main Entry Point: dev_commit_init()
# ══════════════════════════════════════════════════════════════════════════════

def dev_commit_init(db=None) -> dict:
    """
    The Genesis startup sequence. Idempotent — safe to call on every restart.

    Steps:
      1. validate_secrets()
      2. create_genesis_block()
      3. init_node_state_machine()
      4. commit_genesis() → SQLite lineage chain
      5. Update state machine tip
      6. Return status dict

    Args:
        db: SQLAlchemy Session. If None, creates one from SessionLocal.

    Returns:
        {
          "status":        "Genesis_Committed" | "Genesis_Already_Exists",
          "tip":           int,
          "genesis_hash":  str,
          "node_id":       str,
          "node_state":    str,
          "secrets":       dict,
          "timestamp":     str,
        }
    """
    log.info("=" * 60)
    log.info("[INIT] OpenClaw Colony DEV_COMMIT_INIT starting...")
    log.info("[INIT] Node: %s @ %s", NODE_ID, NODE_URL)
    log.info("[INIT] Peers: %d configured", len(PEER_URLS))
    log.info("[INIT] Dev mode: %s", DEV_MODE)
    log.info("=" * 60)

    # ── Step 1: Validate secrets ──────────────────────────────────────────────
    secret_results = validate_secrets(strict=not DEV_MODE)

    # ── Step 2: Create genesis block ──────────────────────────────────────────
    genesis_block = create_genesis_block(node_id=NODE_ID)

    # ── Step 3: Initialise state machine singleton ────────────────────────────
    try:
        sm = get_node_state_machine()
        log.info("[INIT] State machine already initialised (state=%s)", sm.state.value)
    except RuntimeError:
        sm = init_node_state_machine(
            node_id   = NODE_ID,
            node_url  = NODE_URL,
            peer_urls = PEER_URLS,
            admin_key = ADMIN_KEY,
        )
        log.info("[INIT] State machine initialised (state=%s)", sm.state.value)

    # ── Step 4: Commit genesis to SQLite lineage chain ────────────────────────
    _own_db = False
    tip = 0
    freshly_committed = False
    genesis_hash = genesis_block["lineage_hash"]

    if db is None:
        if Base is not None and engine is not None:
            Base.metadata.create_all(bind=engine)
        if SessionLocal is not None:
            db = SessionLocal()
            _own_db = True

    try:
        try:
            if init_federation_tables is not None:
                init_federation_tables()
        except Exception as exc:
            log.warning("[INIT] Federation tables init skipped: %s", exc)

        try:
            if init_biometric_tables is not None:
                init_biometric_tables()
        except Exception as exc:
            log.warning("[INIT] Biometric tables init skipped: %s", exc)

        freshly_committed, genesis_hash = commit_genesis(genesis_block, db)

        tip = db.query(LineageRecord).count() if LineageRecord is not None else 0

        sm.update_our_tip(tip)

    finally:
        if _own_db and db is not None:
            db.close()

    # ── Step 5: Capture final state ───────────────────────────────────────────
    current_state = sm.state
    log.info("[INIT] Node state: %s", current_state.value)

    # ── Step 6: Build and return status dict ──────────────────────────────────
    status = "Genesis_Committed" if freshly_committed else "Genesis_Already_Exists"

    result = {
        "status":       status,
        "tip":          tip,
        "genesis_hash": genesis_hash,
        "node_id":      NODE_ID,
        "node_url":     NODE_URL,
        "node_state":   current_state.value,
        "peers":        len(PEER_URLS),
        "dev_mode":     DEV_MODE,
        "secrets":      secret_results,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    }

    log.info("=" * 60)
    log.info("[INIT] ✅ DEV_COMMIT_INIT complete")
    log.info("[INIT]    status:       %s", status)
    log.info("[INIT]    tip:          %d", tip)
    log.info("[INIT]    genesis_hash: %s...", genesis_hash[:16])
    log.info("[INIT]    node_state:   %s", current_state.value)
    log.info("=" * 60)

    return result


# ══════════════════════════════════════════════════════════════════════════════
# CLI runner — python dev_commit_init.py
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    import json as _json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    try:
        result = dev_commit_init()
        print("\n" + "=" * 60)
        print("DEV_COMMIT_INIT RESULT:")
        print(_json.dumps(result, indent=2, default=str))
        print("=" * 60)
        sys.exit(0)
    except SecretValidationError as e:
        print(f"\n[FATAL] {e}", file=sys.stderr)
        print("\nTo run in dev mode without secrets:", file=sys.stderr)
        print("  export COLONY_DEV_MODE=true", file=sys.stderr)
        print("  python dev_commit_init.py", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n[FATAL] Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)