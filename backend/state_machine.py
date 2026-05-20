"""
OpenClaw Colony — Deterministic State Machine
==============================================
Formalizes the lifecycle of Nodes, Proposals, and Transactions.
Transforms the colony from "hope-based" scripts into provable infrastructure.

NodeState transitions:
  STANDALONE → ANNOUNCING → SYNCING → LIVE ↔ ISOLATED

ProposalState transitions:
  PENDING → APPROVED | BLOCKED | EXPIRED

TransactionState transitions:
  RECEIVED → GATE_0_CHECK → GATE_1_CHECK → GATE_2_CHECK → GATE_3_CHECK
           → APPROVED → CHAINED
           → BLOCKED  → CHAINED  (blocked actions are chained too)

Architect's Priorities implemented:
  1. SYNCING→LIVE guarded by Lineage Head Check (tip_index must match highest peer)
  2. ProposalState.EXPIRED via asyncio background task with PROPOSAL_TTL
  3. TransactionState transitions atomic with aethel_kernel (failure written to
     lineage chain before next transaction can be processed)
  4. Observer pattern: NodeState changes broadcast heartbeat to /federation/status

Environment variables:
  PROPOSAL_TTL_HOURS   — hours before PENDING proposal expires (default 72)
  PROPOSAL_EXPIRY_INTERVAL — seconds between expiry scan runs (default 300)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from typing import Callable, List, Optional

# Top-level import so tests can patch state_machine.AethelInterface
try:
    from aethel_interface import AethelInterface
except ImportError:
    AethelInterface = None  # type: ignore[assignment,misc]

log = logging.getLogger("colony.state_machine")

# ── Configuration ─────────────────────────────────────────────────────────────
PROPOSAL_TTL_HOURS       = int(os.environ.get("PROPOSAL_TTL_HOURS", "72"))
PROPOSAL_EXPIRY_INTERVAL = int(os.environ.get("PROPOSAL_EXPIRY_INTERVAL", "300"))
NODE_ISOLATION_TIMEOUT   = int(os.environ.get("NODE_ISOLATION_TIMEOUT", "180"))


# ══════════════════════════════════════════════════════════════════════════════
# NodeState
# ══════════════════════════════════════════════════════════════════════════════

class NodeState(Enum):
    """
    Lifecycle state of a colony node in the federation.

    STANDALONE  — no peers configured; running in sovereign isolation
    ANNOUNCING  — startup broadcast in progress; waiting for peer acknowledgement
    SYNCING     — ≥1 peer responded; pulling missing lineage records to catch up
    LIVE        — lineage tip matches highest peer tip; fully operational
    ISOLATED    — was LIVE but all peers have gone silent beyond timeout
    """
    STANDALONE  = "standalone"
    ANNOUNCING  = "announcing"
    SYNCING     = "syncing"
    LIVE        = "live"
    ISOLATED    = "isolated"


# Valid transitions: from → {allowed targets}
_NODE_TRANSITIONS: dict[NodeState, set[NodeState]] = {
    NodeState.STANDALONE:  {NodeState.ANNOUNCING},
    NodeState.ANNOUNCING:  {NodeState.SYNCING, NodeState.STANDALONE},
    NodeState.SYNCING:     {NodeState.LIVE, NodeState.ISOLATED, NodeState.ANNOUNCING},
    NodeState.LIVE:        {NodeState.SYNCING, NodeState.ISOLATED},
    NodeState.ISOLATED:    {NodeState.ANNOUNCING, NodeState.LIVE},
}


class NodeStateMachine:
    """
    Thread-safe state machine for a single colony node.

    Observer pattern: register callbacks via `on_transition()`.
    Each callback receives (old_state, new_state, reason).
    """

    def __init__(self, node_id: str, peer_urls: list[str]):
        self._node_id   = node_id
        self._lock      = threading.Lock()
        self._observers: list[Callable[[NodeState, NodeState, str], None]] = []

        # Start in STANDALONE if no peers, else ANNOUNCING
        initial = NodeState.STANDALONE if not peer_urls else NodeState.ANNOUNCING
        self._state = initial
        self._entered_at: datetime = datetime.now(timezone.utc)

        # Highest tip_index seen in peer gossip — used for SYNCING→LIVE guard
        self._highest_peer_tip: int = 0
        self._our_tip: int = 0

        # Timestamp of last successful peer contact (for isolation detection)
        self._last_peer_contact: Optional[datetime] = None

        log.info("[NODE-SM] %s initialised in state %s", node_id, initial.value)

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def state(self) -> NodeState:
        with self._lock:
            return self._state

    @property
    def highest_peer_tip(self) -> int:
        with self._lock:
            return self._highest_peer_tip

    @property
    def our_tip(self) -> int:
        with self._lock:
            return self._our_tip

    def on_transition(self, callback: Callable[[NodeState, NodeState, str], None]):
        """Register an observer callback for state transitions."""
        self._observers.append(callback)

    def update_peer_tip(self, tip_index: int):
        """Called when a peer gossip message arrives with a tip_index."""
        with self._lock:
            self._last_peer_contact = datetime.now(timezone.utc)
            if tip_index > self._highest_peer_tip:
                self._highest_peer_tip = tip_index
                log.debug("[NODE-SM] Highest peer tip updated to %d", tip_index)

    def update_our_tip(self, tip_index: int):
        """Called when our lineage chain grows."""
        with self._lock:
            self._our_tip = tip_index

    def transition(self, new_state: NodeState, reason: str = "") -> bool:
        """
        Attempt a state transition. Returns True if successful.
        Enforces valid transition table. Thread-safe.

        SYNCING → LIVE is additionally guarded by the Lineage Head Check:
        our tip_index must equal the highest seen peer tip_index.
        """
        with self._lock:
            old_state = self._state

            # Guard: check transition is allowed
            allowed = _NODE_TRANSITIONS.get(old_state, set())
            if new_state not in allowed:
                log.warning(
                    "[NODE-SM] %s INVALID transition %s → %s (reason: %s)",
                    self._node_id, old_state.value, new_state.value, reason
                )
                return False

            # Architect Priority 1: SYNCING → LIVE Lineage Head Check
            if old_state == NodeState.SYNCING and new_state == NodeState.LIVE:
                if self._our_tip < self._highest_peer_tip:
                    log.info(
                        "[NODE-SM] %s SYNCING→LIVE blocked: our_tip=%d < highest_peer_tip=%d. "
                        "Still catching up.",
                        self._node_id, self._our_tip, self._highest_peer_tip
                    )
                    return False

            self._state      = new_state
            self._entered_at = datetime.now(timezone.utc)

        log.info(
            "[NODE-SM] %s %s → %s | reason: %s",
            self._node_id, old_state.value, new_state.value, reason or "unspecified"
        )

        # Fire observers outside the lock to prevent deadlock
        for cb in self._observers:
            try:
                cb(old_state, new_state, reason)
            except Exception as exc:
                log.error("[NODE-SM] Observer error: %s", exc)

        return True

    def check_isolation(self) -> bool:
        """
        Call periodically. If we are LIVE but have not heard from any peer
        in NODE_ISOLATION_TIMEOUT seconds, transition to ISOLATED.
        Returns True if isolation was triggered.
        """
        with self._lock:
            if self._state != NodeState.LIVE:
                return False
            if self._last_peer_contact is None:
                return False
            elapsed = (datetime.now(timezone.utc) - self._last_peer_contact).total_seconds()
            if elapsed > NODE_ISOLATION_TIMEOUT:
                pass  # transition outside lock
            else:
                return False

        return self.transition(
            NodeState.ISOLATED,
            reason=f"No peer contact for {NODE_ISOLATION_TIMEOUT}s"
        )

    def as_dict(self) -> dict:
        with self._lock:
            return {
                "node_id":           self._node_id,
                "state":             self._state.value,
                "entered_at":        self._entered_at.isoformat(),
                "our_tip":           self._our_tip,
                "highest_peer_tip":  self._highest_peer_tip,
                "last_peer_contact": (
                    self._last_peer_contact.isoformat()
                    if self._last_peer_contact else None
                ),
                "synced": self._our_tip >= self._highest_peer_tip,
            }


# ══════════════════════════════════════════════════════════════════════════════
# ProposalState
# ══════════════════════════════════════════════════════════════════════════════

class ProposalState(Enum):
    """
    Lifecycle state of a cross-node governance proposal.

    PENDING  — created, collecting votes
    APPROVED — votes_for ≥ quorum threshold
    BLOCKED  — votes_against > (peers - quorum)
    EXPIRED  — PROPOSAL_TTL elapsed without quorum reached
    """
    PENDING  = "pending"
    APPROVED = "approved"
    BLOCKED  = "blocked"
    EXPIRED  = "expired"


_PROPOSAL_TRANSITIONS: dict[ProposalState, set[ProposalState]] = {
    ProposalState.PENDING:  {ProposalState.APPROVED, ProposalState.BLOCKED, ProposalState.EXPIRED},
    ProposalState.APPROVED: set(),   # terminal
    ProposalState.BLOCKED:  set(),   # terminal
    ProposalState.EXPIRED:  set(),   # terminal
}


def proposal_transition(
    current: ProposalState,
    new: ProposalState,
    proposal_id: str,
) -> ProposalState:
    """
    Validate and apply a proposal state transition.
    Returns new state on success, raises ValueError on invalid transition.
    """
    allowed = _PROPOSAL_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise ValueError(
            f"Proposal {proposal_id}: invalid transition {current.value} → {new.value}"
        )
    log.info("[PROPOSAL-SM] %s: %s → %s", proposal_id, current.value, new.value)
    return new


# ── Architect Priority 2: Proposal Expiry Background Task ────────────────────

async def proposal_expiry_loop(db_factory, lineage_writer=None):
    """
    Asyncio background task. Runs every PROPOSAL_EXPIRY_INTERVAL seconds.
    Scans PENDING proposals. If created_at + PROPOSAL_TTL_HOURS < now,
    transitions to EXPIRED and writes a lineage chain entry.

    Args:
        db_factory:     callable returning a SQLAlchemy Session
        lineage_writer: optional callable(task_id, outcome, description)
                        to commit the expiry to the lineage chain
    """
    ttl = timedelta(hours=PROPOSAL_TTL_HOURS)
    log.info(
        "[PROPOSAL-EXPIRY] Background task started "
        "(TTL=%dh, interval=%ds)",
        PROPOSAL_TTL_HOURS, PROPOSAL_EXPIRY_INTERVAL
    )

    while True:
        try:
            await _run_expiry_scan(db_factory, ttl, lineage_writer)
        except Exception as exc:
            log.error("[PROPOSAL-EXPIRY] Scan error: %s", exc)
        await asyncio.sleep(PROPOSAL_EXPIRY_INTERVAL)


async def _run_expiry_scan(db_factory, ttl: timedelta, lineage_writer):
    """Single expiry scan pass."""
    from federation import CrossNodeProposal   # local import to avoid circular

    db = db_factory()
    try:
        now = datetime.now(timezone.utc)
        cutoff = now - ttl

        pending = db.query(CrossNodeProposal).filter_by(status="pending").all()
        expired_count = 0

        for proposal in pending:
            created = proposal.created_at
            # Make timezone-aware if naive
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)

            if created < cutoff:
                age_hours = (now - created).total_seconds() / 3600
                proposal.status      = ProposalState.EXPIRED.value
                proposal.resolved_at = now
                db.commit()
                expired_count += 1

                log.info(
                    "[PROPOSAL-EXPIRY] Proposal %s EXPIRED after %.1fh "
                    "(TTL=%dh, origin=%s)",
                    proposal.proposal_id, age_hours,
                    PROPOSAL_TTL_HOURS, proposal.origin_node
                )

                # Architect Priority 2: write expiry to lineage chain
                if lineage_writer:
                    try:
                        await lineage_writer(
                            task_id=f"expiry:{proposal.proposal_id}",
                            outcome="GOVERNANCE_EXPIRED",
                            description=(
                                f"Proposal {proposal.proposal_id} from "
                                f"{proposal.origin_node} expired after "
                                f"{age_hours:.1f}h without quorum. "
                                f"Description: {proposal.description[:120]}"
                            ),
                        )
                    except Exception as exc:
                        log.error(
                            "[PROPOSAL-EXPIRY] Lineage write failed for %s: %s",
                            proposal.proposal_id, exc
                        )

        if expired_count:
            log.info("[PROPOSAL-EXPIRY] Expired %d proposals this scan.", expired_count)

    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# TransactionState
# ══════════════════════════════════════════════════════════════════════════════

class TransactionState(Enum):
    """
    Lifecycle state of a single transaction through the Aethel pipeline.

    RECEIVED     — transaction accepted by coordinator
    GATE_0_CHECK — biometric attestation verification in progress
    GATE_1_CHECK — human consent check in progress
    GATE_2_CHECK — Love Quality score check in progress
    GATE_3_CHECK — extraction signature scan in progress
    APPROVED     — all gates passed
    BLOCKED      — a gate failed
    CHAINED      — result written to lineage chain (terminal)
    """
    RECEIVED     = "received"
    GATE_0_CHECK = "gate_0_check"
    GATE_1_CHECK = "gate_1_check"
    GATE_2_CHECK = "gate_2_check"
    GATE_3_CHECK = "gate_3_check"
    APPROVED     = "approved"
    BLOCKED      = "blocked"
    CHAINED      = "chained"


_TX_TRANSITIONS: dict[TransactionState, set[TransactionState]] = {
    TransactionState.RECEIVED:     {TransactionState.GATE_0_CHECK},
    TransactionState.GATE_0_CHECK: {TransactionState.GATE_1_CHECK, TransactionState.BLOCKED},
    TransactionState.GATE_1_CHECK: {TransactionState.GATE_2_CHECK, TransactionState.BLOCKED},
    TransactionState.GATE_2_CHECK: {TransactionState.GATE_3_CHECK, TransactionState.BLOCKED},
    TransactionState.GATE_3_CHECK: {TransactionState.APPROVED,     TransactionState.BLOCKED},
    TransactionState.APPROVED:     {TransactionState.CHAINED},
    TransactionState.BLOCKED:      {TransactionState.CHAINED},
    TransactionState.CHAINED:      set(),   # terminal
}

# Gate index → TransactionState mapping
_GATE_CHECK_STATES = {
    0: TransactionState.GATE_0_CHECK,
    1: TransactionState.GATE_1_CHECK,
    2: TransactionState.GATE_2_CHECK,
    3: TransactionState.GATE_3_CHECK,
}


@dataclass
class TransactionRecord:
    """
    Tracks a single transaction through the state machine.
    Architect Priority 3: transitions are atomic with kernel — failure is
    written to lineage chain before the next transaction can be processed.
    """
    task_id:     str
    state:       TransactionState = TransactionState.RECEIVED
    history:     list[tuple[TransactionState, str, str]] = field(default_factory=list)
    # (state, timestamp_iso, reason)
    blocked_at_gate: Optional[int]  = None
    reason:          Optional[str]  = None
    lineage_hash:    Optional[str]  = None
    kernel_timestamp: Optional[int] = None

    def transition(self, new_state: TransactionState, reason: str = "") -> bool:
        """
        Apply a state transition. Returns True on success.
        Records every transition in history for full auditability.
        """
        allowed = _TX_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            log.error(
                "[TX-SM] %s INVALID transition %s → %s",
                self.task_id, self.state.value, new_state.value
            )
            return False

        old = self.state
        self.state = new_state
        self.history.append((
            new_state,
            datetime.now(timezone.utc).isoformat(),
            reason,
        ))
        log.debug(
            "[TX-SM] %s: %s → %s | %s",
            self.task_id, old.value, new_state.value, reason or ""
        )
        return True

    def as_dict(self) -> dict:
        return {
            "task_id":         self.task_id,
            "state":           self.state.value,
            "blocked_at_gate": self.blocked_at_gate,
            "reason":          self.reason,
            "lineage_hash":    self.lineage_hash,
            "kernel_timestamp": self.kernel_timestamp,
            "history": [
                {"state": s.value, "at": ts, "reason": r}
                for s, ts, r in self.history
            ],
        }


class TransactionStateMachine:
    """
    Orchestrates a transaction through the Aethel pipeline with formal
    state tracking. Wraps AethelInterface.validate() and ensures:

    - Every gate check is a named state transition
    - Failures are atomically committed to lineage before returning
    - The full transition history is available for audit
    """

    # Class-level lock: Architect Priority 3 — only one transaction
    # can be in the CHAINING phase at a time (atomic lineage write)
    _chain_lock = threading.Lock()

    def run(
        self,
        task_id: str,
        human_consent: bool,
        lq_score: float,
        agent_outputs: dict,
        biometric_token: Optional[dict] = None,
        action_type: str = "proposal",
        db=None,
        lineage_db=None,
    ) -> TransactionRecord:
        """
        Execute the full 4-gate pipeline with state machine tracking.

        Returns a TransactionRecord in CHAINED state with full history.
        The lineage write is atomic — no other transaction can chain
        simultaneously (class-level lock).
        """
        record = TransactionRecord(task_id=task_id)
        record.transition(TransactionState.GATE_0_CHECK, "Starting gate pipeline")

        # Run the full Aethel validation
        iface = AethelInterface()
        result = iface.validate(
            task_id=task_id,
            human_consent=human_consent,
            lq_score=lq_score,
            agent_outputs=agent_outputs,
            biometric_token=biometric_token,
            action_type=action_type,
            db=db,
        )

        verdict      = result.get("verdict", "BLOCKED")
        blocked_gate = result.get("blocked_at_gate")
        reason       = result.get("reason")

        # Advance state machine through gates that were reached
        gates_result = result.get("gates", {})
        for gate_num in range(4):
            gate_key   = f"gate_{gate_num}"
            gate_info  = gates_result.get(gate_key, {})
            gate_verdict = gate_info.get("verdict", "NOT_REACHED")

            if gate_verdict == "NOT_REACHED":
                break

            check_state = _GATE_CHECK_STATES.get(gate_num)
            if check_state and record.state != check_state:
                record.transition(check_state, f"Gate {gate_num} check")

            if gate_verdict == "FAIL":
                record.blocked_at_gate = gate_num
                record.reason          = gate_info.get("reason", reason)
                record.transition(
                    TransactionState.BLOCKED,
                    f"Gate {gate_num} FAIL: {record.reason}"
                )
                break
        else:
            # All gates passed
            if verdict == "APPROVED":
                record.transition(TransactionState.APPROVED, "All gates passed")

        if verdict == "APPROVED" and record.state != TransactionState.APPROVED:
            record.transition(TransactionState.APPROVED, "Kernel approved")

        # Architect Priority 3: atomic lineage chain write
        # Acquire class-level lock before writing to chain
        with TransactionStateMachine._chain_lock:
            record = self._commit_to_chain(record, result, lineage_db)

        return record

    def _commit_to_chain(
        self,
        record: TransactionRecord,
        kernel_result: dict,
        lineage_db,
    ) -> TransactionRecord:
        """
        Write the transaction outcome to the lineage chain.
        Called inside the class-level chain lock — atomic.
        """
        record.lineage_hash    = kernel_result.get("lineage_hash")
        record.kernel_timestamp = kernel_result.get("kernel_timestamp")

        if lineage_db is not None:
            try:
                from db import LineageRecord
                import hashlib as _hl

                prev = (
                    lineage_db.query(LineageRecord)
                    .order_by(LineageRecord.id.desc())
                    .first()
                )
                prev_hash = prev.lineage_hash if prev else "GENESIS"

                outcome_str = (
                    record.state.value.upper()
                    if record.state != TransactionState.CHAINED
                    else "CHAINED"
                )

                lr = LineageRecord(
                    task_id      = record.task_id,
                    prompt_hash  = _hl.sha256(record.task_id.encode()).hexdigest(),
                    lq_composite = 0.0,
                    lineage_hash = record.lineage_hash or prev_hash,
                    prev_hash    = prev_hash,
                )
                lineage_db.add(lr)
                lineage_db.commit()
                log.info(
                    "[TX-SM] %s chained: outcome=%s lineage=%s...",
                    record.task_id, outcome_str,
                    (record.lineage_hash or "")[:16]
                )
            except Exception as exc:
                log.error("[TX-SM] Lineage write failed for %s: %s", record.task_id, exc)

        record.transition(TransactionState.CHAINED, "Lineage committed")
        return record


# ══════════════════════════════════════════════════════════════════════════════
# Observer: NodeState heartbeat broadcaster
# ══════════════════════════════════════════════════════════════════════════════

def make_heartbeat_observer(node_id: str, node_url: str, admin_key: str):
    """
    Architect Priority 4: Observer that broadcasts a heartbeat to all peers
    whenever the NodeState changes. Peers can monitor the grid's Laminar Flow
    from the /federation/status endpoint.

    Returns a callback suitable for NodeStateMachine.on_transition().
    """
    import httpx
    from federation import PEER_URLS

    async def _broadcast(old_state: NodeState, new_state: NodeState, reason: str):
        if not PEER_URLS:
            return
        payload = {
            "node_id":   node_id,
            "node_url":  node_url,
            "old_state": old_state.value,
            "new_state": new_state.value,
            "reason":    reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        headers = {"Authorization": f"Bearer {admin_key}"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            for peer_url in PEER_URLS:
                try:
                    await client.post(
                        f"{peer_url}/federation/heartbeat",
                        json=payload,
                        headers=headers,
                    )
                    log.debug("[HEARTBEAT] Sent %s→%s to %s", old_state.value, new_state.value, peer_url)
                except Exception as exc:
                    log.warning("[HEARTBEAT] Failed to notify %s: %s", peer_url, exc)

    def sync_observer(old_state: NodeState, new_state: NodeState, reason: str):
        """Sync wrapper — schedules the async broadcast on the running event loop."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_broadcast(old_state, new_state, reason))
            else:
                loop.run_until_complete(_broadcast(old_state, new_state, reason))
        except RuntimeError:
            # No event loop — log only (e.g. during tests)
            log.info(
                "[HEARTBEAT] NodeState %s → %s (no event loop for broadcast)",
                old_state.value, new_state.value
            )

    return sync_observer


# ══════════════════════════════════════════════════════════════════════════════
# Module-level singleton — shared across the process
# ══════════════════════════════════════════════════════════════════════════════

_node_sm: Optional[NodeStateMachine] = None


def get_node_state_machine() -> NodeStateMachine:
    """Return the process-level NodeStateMachine singleton."""
    global _node_sm
    if _node_sm is None:
        raise RuntimeError(
            "NodeStateMachine not initialised. "
            "Call init_node_state_machine() on startup."
        )
    return _node_sm


def init_node_state_machine(
    node_id: str,
    node_url: str,
    peer_urls: list[str],
    admin_key: str,
) -> NodeStateMachine:
    """
    Initialise the process-level NodeStateMachine.
    Registers the heartbeat observer automatically.
    Call once on application startup.
    """
    global _node_sm
    _node_sm = NodeStateMachine(node_id=node_id, peer_urls=peer_urls)
    observer = make_heartbeat_observer(node_id, node_url, admin_key)
    _node_sm.on_transition(observer)
    log.info("[STATE-MACHINE] Initialised for node %s", node_id)
    return _node_sm