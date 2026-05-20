"""
OpenClaw Colony — State Machine Tests
======================================
Covers NodeState, ProposalState, and TransactionState machines.
Tests all Architect's Priorities:
  1. SYNCING→LIVE lineage head check guard
  2. Proposal expiry background task
  3. TransactionState atomic transitions with kernel
  4. Observer/heartbeat pattern
"""

import asyncio
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from state_machine import (
    NodeState,
    NodeStateMachine,
    ProposalState,
    TransactionRecord,
    TransactionState,
    TransactionStateMachine,
    _NODE_TRANSITIONS,
    _PROPOSAL_TRANSITIONS,
    _TX_TRANSITIONS,
    init_node_state_machine,
    get_node_state_machine,
    proposal_transition,
    _run_expiry_scan,
    PROPOSAL_TTL_HOURS,
)


# ══════════════════════════════════════════════════════════════════════════════
# NodeState Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestNodeStateMachine:

    def test_initial_state_standalone_no_peers(self):
        sm = NodeStateMachine(node_id="test-node", peer_urls=[])
        assert sm.state == NodeState.STANDALONE

    def test_initial_state_announcing_with_peers(self):
        sm = NodeStateMachine(node_id="test-node", peer_urls=["http://peer1"])
        assert sm.state == NodeState.ANNOUNCING

    def test_valid_transition_standalone_to_announcing(self):
        sm = NodeStateMachine(node_id="test-node", peer_urls=[])
        assert sm.state == NodeState.STANDALONE
        result = sm.transition(NodeState.ANNOUNCING, "peers added")
        assert result is True
        assert sm.state == NodeState.ANNOUNCING

    def test_valid_transition_announcing_to_syncing(self):
        sm = NodeStateMachine(node_id="test-node", peer_urls=["http://peer1"])
        result = sm.transition(NodeState.SYNCING, "peer responded")
        assert result is True
        assert sm.state == NodeState.SYNCING

    def test_invalid_transition_standalone_to_live(self):
        sm = NodeStateMachine(node_id="test-node", peer_urls=[])
        result = sm.transition(NodeState.LIVE, "skip syncing")
        assert result is False
        assert sm.state == NodeState.STANDALONE

    def test_invalid_transition_live_to_standalone(self):
        sm = NodeStateMachine(node_id="test-node", peer_urls=["http://peer1"])
        sm.transition(NodeState.SYNCING, "peer responded")
        sm.update_peer_tip(5)
        sm.update_our_tip(5)
        sm.transition(NodeState.LIVE, "caught up")
        result = sm.transition(NodeState.STANDALONE, "invalid")
        assert result is False
        assert sm.state == NodeState.LIVE

    # ── Architect Priority 1: SYNCING → LIVE Lineage Head Check ──────────────

    def test_syncing_to_live_blocked_when_behind(self):
        """SYNCING→LIVE must be blocked if our tip < highest peer tip."""
        sm = NodeStateMachine(node_id="test-node", peer_urls=["http://peer1"])
        sm.transition(NodeState.SYNCING, "peer responded")
        sm.update_peer_tip(100)   # peer is at 100
        sm.update_our_tip(50)     # we are only at 50
        result = sm.transition(NodeState.LIVE, "attempt promotion")
        assert result is False
        assert sm.state == NodeState.SYNCING

    def test_syncing_to_live_allowed_when_caught_up(self):
        """SYNCING→LIVE must succeed when our tip >= highest peer tip."""
        sm = NodeStateMachine(node_id="test-node", peer_urls=["http://peer1"])
        sm.transition(NodeState.SYNCING, "peer responded")
        sm.update_peer_tip(100)
        sm.update_our_tip(100)    # caught up
        result = sm.transition(NodeState.LIVE, "lineage head check passed")
        assert result is True
        assert sm.state == NodeState.LIVE

    def test_syncing_to_live_allowed_when_ahead(self):
        """SYNCING→LIVE must succeed when our tip > highest peer tip."""
        sm = NodeStateMachine(node_id="test-node", peer_urls=["http://peer1"])
        sm.transition(NodeState.SYNCING, "peer responded")
        sm.update_peer_tip(50)
        sm.update_our_tip(75)     # we are ahead
        result = sm.transition(NodeState.LIVE, "lineage head check passed")
        assert result is True
        assert sm.state == NodeState.LIVE

    def test_syncing_to_live_allowed_with_no_peers_seen(self):
        """If no peer tip seen yet (highest=0), our tip=0 should allow LIVE."""
        sm = NodeStateMachine(node_id="test-node", peer_urls=["http://peer1"])
        sm.transition(NodeState.SYNCING, "peer responded")
        # No update_peer_tip called — highest_peer_tip = 0
        sm.update_our_tip(0)
        result = sm.transition(NodeState.LIVE, "no peers seen yet")
        assert result is True

    def test_live_to_syncing_when_peer_ahead(self):
        """LIVE→SYNCING is valid when a peer is detected ahead."""
        sm = NodeStateMachine(node_id="test-node", peer_urls=["http://peer1"])
        sm.transition(NodeState.SYNCING, "peer responded")
        sm.update_peer_tip(10)
        sm.update_our_tip(10)
        sm.transition(NodeState.LIVE, "caught up")
        # Peer gets ahead
        sm.update_peer_tip(20)
        result = sm.transition(NodeState.SYNCING, "peer ahead")
        assert result is True
        assert sm.state == NodeState.SYNCING

    def test_live_to_isolated_on_timeout(self):
        """LIVE→ISOLATED when no peer contact beyond timeout."""
        sm = NodeStateMachine(node_id="test-node", peer_urls=["http://peer1"])
        sm.transition(NodeState.SYNCING, "peer responded")
        sm.update_peer_tip(0)
        sm.update_our_tip(0)
        sm.transition(NodeState.LIVE, "caught up")

        # Simulate last contact being far in the past
        past = datetime.now(timezone.utc) - timedelta(seconds=9999)
        sm._last_peer_contact = past

        result = sm.check_isolation()
        assert result is True
        assert sm.state == NodeState.ISOLATED

    def test_no_isolation_when_recently_contacted(self):
        """No isolation if peer was recently seen."""
        sm = NodeStateMachine(node_id="test-node", peer_urls=["http://peer1"])
        sm.transition(NodeState.SYNCING, "peer responded")
        sm.update_peer_tip(0)
        sm.update_our_tip(0)
        sm.transition(NodeState.LIVE, "caught up")
        sm.update_peer_tip(0)   # sets last_peer_contact to now
        result = sm.check_isolation()
        assert result is False
        assert sm.state == NodeState.LIVE

    # ── Architect Priority 4: Observer pattern ────────────────────────────────

    def test_observer_called_on_transition(self):
        """Observer callback must be called on every valid transition."""
        sm = NodeStateMachine(node_id="test-node", peer_urls=[])
        calls = []
        sm.on_transition(lambda old, new, reason: calls.append((old, new, reason)))
        sm.transition(NodeState.ANNOUNCING, "test")
        assert len(calls) == 1
        assert calls[0][0] == NodeState.STANDALONE
        assert calls[0][1] == NodeState.ANNOUNCING

    def test_observer_not_called_on_invalid_transition(self):
        """Observer must NOT be called when transition is rejected."""
        sm = NodeStateMachine(node_id="test-node", peer_urls=[])
        calls = []
        sm.on_transition(lambda old, new, reason: calls.append((old, new, reason)))
        sm.transition(NodeState.LIVE, "invalid")   # STANDALONE→LIVE not allowed
        assert len(calls) == 0

    def test_multiple_observers(self):
        """Multiple observers must all be called."""
        sm = NodeStateMachine(node_id="test-node", peer_urls=[])
        calls_a, calls_b = [], []
        sm.on_transition(lambda o, n, r: calls_a.append(n))
        sm.on_transition(lambda o, n, r: calls_b.append(n))
        sm.transition(NodeState.ANNOUNCING, "test")
        assert len(calls_a) == 1
        assert len(calls_b) == 1

    def test_observer_exception_does_not_break_transition(self):
        """A crashing observer must not prevent the state transition."""
        sm = NodeStateMachine(node_id="test-node", peer_urls=[])
        sm.on_transition(lambda o, n, r: (_ for _ in ()).throw(RuntimeError("boom")))
        result = sm.transition(NodeState.ANNOUNCING, "test")
        assert result is True
        assert sm.state == NodeState.ANNOUNCING

    def test_as_dict_structure(self):
        sm = NodeStateMachine(node_id="node-001", peer_urls=["http://peer1"])
        d = sm.as_dict()
        assert d["node_id"] == "node-001"
        assert d["state"] == NodeState.ANNOUNCING.value
        assert "our_tip" in d
        assert "highest_peer_tip" in d
        assert "synced" in d

    def test_thread_safety(self):
        """Concurrent transitions must not corrupt state."""
        sm = NodeStateMachine(node_id="test-node", peer_urls=[])
        errors = []

        def worker():
            try:
                sm.transition(NodeState.ANNOUNCING, "concurrent")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # State must be one of the valid states — not corrupted
        assert sm.state in NodeState


# ══════════════════════════════════════════════════════════════════════════════
# ProposalState Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestProposalState:

    def test_pending_to_approved(self):
        result = proposal_transition(ProposalState.PENDING, ProposalState.APPROVED, "p1")
        assert result == ProposalState.APPROVED

    def test_pending_to_blocked(self):
        result = proposal_transition(ProposalState.PENDING, ProposalState.BLOCKED, "p1")
        assert result == ProposalState.BLOCKED

    def test_pending_to_expired(self):
        result = proposal_transition(ProposalState.PENDING, ProposalState.EXPIRED, "p1")
        assert result == ProposalState.EXPIRED

    def test_approved_is_terminal(self):
        with pytest.raises(ValueError):
            proposal_transition(ProposalState.APPROVED, ProposalState.PENDING, "p1")

    def test_blocked_is_terminal(self):
        with pytest.raises(ValueError):
            proposal_transition(ProposalState.BLOCKED, ProposalState.PENDING, "p1")

    def test_expired_is_terminal(self):
        with pytest.raises(ValueError):
            proposal_transition(ProposalState.EXPIRED, ProposalState.APPROVED, "p1")

    def test_approved_cannot_become_blocked(self):
        with pytest.raises(ValueError):
            proposal_transition(ProposalState.APPROVED, ProposalState.BLOCKED, "p1")

    def test_all_terminal_states_have_no_transitions(self):
        for terminal in (ProposalState.APPROVED, ProposalState.BLOCKED, ProposalState.EXPIRED):
            assert _PROPOSAL_TRANSITIONS[terminal] == set()


# ── Architect Priority 2: Proposal Expiry ────────────────────────────────────

class TestProposalExpiry:

    @pytest.mark.asyncio
    async def test_expired_proposals_are_marked(self):
        """Proposals older than TTL must be transitioned to EXPIRED."""
        # Build mock DB with one stale pending proposal
        old_time = datetime.now(timezone.utc) - timedelta(hours=PROPOSAL_TTL_HOURS + 1)

        mock_proposal = MagicMock()
        mock_proposal.proposal_id = str(uuid.uuid4())
        mock_proposal.origin_node = "node-001"
        mock_proposal.description = "Test proposal"
        mock_proposal.created_at  = old_time
        mock_proposal.status      = "pending"

        mock_query = MagicMock()
        mock_query.filter_by.return_value.all.return_value = [mock_proposal]

        mock_db = MagicMock()
        mock_db.query.return_value = mock_query

        def db_factory():
            return mock_db

        lineage_calls = []
        async def mock_lineage_writer(task_id, outcome, description):
            lineage_calls.append((task_id, outcome, description))

        await _run_expiry_scan(db_factory, timedelta(hours=PROPOSAL_TTL_HOURS), mock_lineage_writer)

        assert mock_proposal.status == ProposalState.EXPIRED.value
        assert mock_db.commit.called
        assert len(lineage_calls) == 1
        assert lineage_calls[0][1] == "GOVERNANCE_EXPIRED"
        assert mock_proposal.proposal_id in lineage_calls[0][0]

    @pytest.mark.asyncio
    async def test_fresh_proposals_not_expired(self):
        """Proposals within TTL must NOT be expired."""
        fresh_time = datetime.now(timezone.utc) - timedelta(hours=1)

        mock_proposal = MagicMock()
        mock_proposal.proposal_id = str(uuid.uuid4())
        mock_proposal.created_at  = fresh_time
        mock_proposal.status      = "pending"

        mock_query = MagicMock()
        mock_query.filter_by.return_value.all.return_value = [mock_proposal]

        mock_db = MagicMock()
        mock_db.query.return_value = mock_query

        await _run_expiry_scan(lambda: mock_db, timedelta(hours=PROPOSAL_TTL_HOURS), None)

        assert mock_proposal.status == "pending"   # unchanged
        assert not mock_db.commit.called

    @pytest.mark.asyncio
    async def test_expiry_handles_naive_datetime(self):
        """Naive datetimes (no tzinfo) must be handled without crashing."""
        old_time = datetime.utcnow() - timedelta(hours=PROPOSAL_TTL_HOURS + 5)
        # naive — no tzinfo

        mock_proposal = MagicMock()
        mock_proposal.proposal_id = str(uuid.uuid4())
        mock_proposal.origin_node = "node-001"
        mock_proposal.description = "Naive datetime test"
        mock_proposal.created_at  = old_time
        mock_proposal.status      = "pending"

        mock_query = MagicMock()
        mock_query.filter_by.return_value.all.return_value = [mock_proposal]
        mock_db = MagicMock()
        mock_db.query.return_value = mock_query

        # Should not raise
        await _run_expiry_scan(lambda: mock_db, timedelta(hours=PROPOSAL_TTL_HOURS), None)
        assert mock_proposal.status == ProposalState.EXPIRED.value

    @pytest.mark.asyncio
    async def test_expiry_lineage_writer_failure_does_not_crash(self):
        """If lineage writer raises, expiry scan must continue without crashing."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=PROPOSAL_TTL_HOURS + 1)

        mock_proposal = MagicMock()
        mock_proposal.proposal_id = str(uuid.uuid4())
        mock_proposal.origin_node = "node-001"
        mock_proposal.description = "Lineage failure test"
        mock_proposal.created_at  = old_time
        mock_proposal.status      = "pending"

        mock_query = MagicMock()
        mock_query.filter_by.return_value.all.return_value = [mock_proposal]
        mock_db = MagicMock()
        mock_db.query.return_value = mock_query

        async def failing_writer(task_id, outcome, description):
            raise RuntimeError("lineage DB down")

        # Should not raise
        await _run_expiry_scan(lambda: mock_db, timedelta(hours=PROPOSAL_TTL_HOURS), failing_writer)
        assert mock_proposal.status == ProposalState.EXPIRED.value

    @pytest.mark.asyncio
    async def test_multiple_proposals_mixed_expiry(self):
        """Only stale proposals expire; fresh ones are untouched."""
        old_time   = datetime.now(timezone.utc) - timedelta(hours=PROPOSAL_TTL_HOURS + 1)
        fresh_time = datetime.now(timezone.utc) - timedelta(hours=1)

        stale = MagicMock()
        stale.proposal_id = "stale-001"
        stale.origin_node = "node-001"
        stale.description = "Stale"
        stale.created_at  = old_time
        stale.status      = "pending"

        fresh = MagicMock()
        fresh.proposal_id = "fresh-001"
        fresh.created_at  = fresh_time
        fresh.status      = "pending"

        mock_query = MagicMock()
        mock_query.filter_by.return_value.all.return_value = [stale, fresh]
        mock_db = MagicMock()
        mock_db.query.return_value = mock_query

        await _run_expiry_scan(lambda: mock_db, timedelta(hours=PROPOSAL_TTL_HOURS), None)

        assert stale.status == ProposalState.EXPIRED.value
        assert fresh.status == "pending"


# ══════════════════════════════════════════════════════════════════════════════
# TransactionState Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestTransactionRecord:

    def test_initial_state_is_received(self):
        rec = TransactionRecord(task_id="task-001")
        assert rec.state == TransactionState.RECEIVED

    def test_valid_transition_received_to_gate0(self):
        rec = TransactionRecord(task_id="task-001")
        result = rec.transition(TransactionState.GATE_0_CHECK, "starting")
        assert result is True
        assert rec.state == TransactionState.GATE_0_CHECK

    def test_full_approved_path(self):
        """RECEIVED → G0 → G1 → G2 → G3 → APPROVED → CHAINED"""
        rec = TransactionRecord(task_id="task-001")
        path = [
            TransactionState.GATE_0_CHECK,
            TransactionState.GATE_1_CHECK,
            TransactionState.GATE_2_CHECK,
            TransactionState.GATE_3_CHECK,
            TransactionState.APPROVED,
            TransactionState.CHAINED,
        ]
        for state in path:
            result = rec.transition(state, f"moving to {state.value}")
            assert result is True, f"Transition to {state.value} failed"
        assert rec.state == TransactionState.CHAINED

    def test_blocked_at_gate_0(self):
        rec = TransactionRecord(task_id="task-001")
        rec.transition(TransactionState.GATE_0_CHECK)
        rec.transition(TransactionState.BLOCKED, "biometric fail")
        rec.transition(TransactionState.CHAINED, "logged")
        assert rec.state == TransactionState.CHAINED

    def test_blocked_at_gate_2(self):
        rec = TransactionRecord(task_id="task-001")
        rec.transition(TransactionState.GATE_0_CHECK)
        rec.transition(TransactionState.GATE_1_CHECK)
        rec.transition(TransactionState.GATE_2_CHECK)
        rec.transition(TransactionState.BLOCKED, "LQ too low")
        rec.transition(TransactionState.CHAINED, "logged")
        assert rec.state == TransactionState.CHAINED

    def test_invalid_skip_gate(self):
        """Cannot skip from RECEIVED directly to GATE_2_CHECK."""
        rec = TransactionRecord(task_id="task-001")
        result = rec.transition(TransactionState.GATE_2_CHECK, "skip")
        assert result is False
        assert rec.state == TransactionState.RECEIVED

    def test_chained_is_terminal(self):
        """Cannot transition out of CHAINED."""
        rec = TransactionRecord(task_id="task-001")
        rec.transition(TransactionState.GATE_0_CHECK)
        rec.transition(TransactionState.BLOCKED)
        rec.transition(TransactionState.CHAINED)
        result = rec.transition(TransactionState.RECEIVED, "restart")
        assert result is False
        assert rec.state == TransactionState.CHAINED

    def test_history_records_all_transitions(self):
        rec = TransactionRecord(task_id="task-001")
        rec.transition(TransactionState.GATE_0_CHECK, "step 1")
        rec.transition(TransactionState.GATE_1_CHECK, "step 2")
        assert len(rec.history) == 2
        assert rec.history[0][0] == TransactionState.GATE_0_CHECK
        assert rec.history[1][0] == TransactionState.GATE_1_CHECK

    def test_as_dict_structure(self):
        rec = TransactionRecord(task_id="task-abc")
        rec.transition(TransactionState.GATE_0_CHECK)
        d = rec.as_dict()
        assert d["task_id"] == "task-abc"
        assert d["state"] == TransactionState.GATE_0_CHECK.value
        assert isinstance(d["history"], list)
        assert len(d["history"]) == 1

    def test_all_terminal_states_have_no_transitions(self):
        assert _TX_TRANSITIONS[TransactionState.CHAINED] == set()

    def test_approved_cannot_go_to_blocked(self):
        rec = TransactionRecord(task_id="task-001")
        for s in [
            TransactionState.GATE_0_CHECK,
            TransactionState.GATE_1_CHECK,
            TransactionState.GATE_2_CHECK,
            TransactionState.GATE_3_CHECK,
            TransactionState.APPROVED,
        ]:
            rec.transition(s)
        result = rec.transition(TransactionState.BLOCKED, "too late")
        assert result is False
        assert rec.state == TransactionState.APPROVED


# ── Architect Priority 3: Atomic kernel integration ──────────────────────────

class TestTransactionStateMachine:

    def _make_approved_result(self):
        return {
            "verdict": "APPROVED",
            "blocked_at_gate": None,
            "reason": None,
            "lineage_hash": "abc123" * 10,
            "kernel_timestamp": 1700000000,
            "gates": {
                "gate_0": {"verdict": "PASS", "reason": None},
                "gate_1": {"verdict": "PASS", "reason": None},
                "gate_2": {"verdict": "PASS", "reason": None},
                "gate_3": {"verdict": "PASS", "reason": None},
            },
            "actor": None,
        }

    def _make_blocked_result(self, gate: int, reason: str):
        gates = {}
        for g in range(gate):
            gates[f"gate_{g}"] = {"verdict": "PASS", "reason": None}
        gates[f"gate_{gate}"] = {"verdict": "FAIL", "reason": reason}
        for g in range(gate + 1, 4):
            gates[f"gate_{g}"] = {"verdict": "NOT_REACHED", "reason": None}
        return {
            "verdict": "BLOCKED",
            "blocked_at_gate": gate,
            "reason": reason,
            "lineage_hash": "dead" * 16,
            "kernel_timestamp": 1700000000,
            "gates": gates,
            "actor": None,
        }

    def test_approved_transaction_reaches_chained(self):
        sm = TransactionStateMachine()
        with patch("aethel_interface.AethelInterface") as MockIface:
            MockIface.return_value.validate.return_value = self._make_approved_result()
            import state_machine as _sm
            _sm.AethelInterface = MockIface
            record = sm.run(
                task_id="task-approved",
                human_consent=True,
                lq_score=0.91,
                agent_outputs={"summary": "all good"},
                lineage_db=None,
            )
        assert record.state == TransactionState.CHAINED
        assert record.blocked_at_gate is None

    def test_blocked_at_gate_0_reaches_chained(self):
        sm = TransactionStateMachine()
        with patch("aethel_interface.AethelInterface") as MockIface:
            MockIface.return_value.validate.return_value = self._make_blocked_result(
                0, "GATE0_INVALID_SIG: spoof detected"
            )
            import state_machine as _sm
            _sm.AethelInterface = MockIface
            record = sm.run(
                task_id="task-blocked-g0",
                human_consent=True,
                lq_score=0.91,
                agent_outputs={},
                lineage_db=None,
            )
        assert record.state == TransactionState.CHAINED
        assert record.blocked_at_gate == 0

    def test_blocked_at_gate_2_reaches_chained(self):
        sm = TransactionStateMachine()
        with patch("aethel_interface.AethelInterface") as MockIface:
            MockIface.return_value.validate.return_value = self._make_blocked_result(
                2, "GATE2_LQ_SUBTHRESHOLD: score=0.72"
            )
            import state_machine as _sm
            _sm.AethelInterface = MockIface
            record = sm.run(
                task_id="task-blocked-g2",
                human_consent=True,
                lq_score=0.72,
                agent_outputs={},
                lineage_db=None,
            )
        assert record.state == TransactionState.CHAINED
        assert record.blocked_at_gate == 2

    def test_blocked_at_gate_3_reaches_chained(self):
        sm = TransactionStateMachine()
        with patch("aethel_interface.AethelInterface") as MockIface:
            MockIface.return_value.validate.return_value = self._make_blocked_result(
                3, "GATE3_EXTRACTION_SIG: bypass_treasury"
            )
            import state_machine as _sm
            _sm.AethelInterface = MockIface
            record = sm.run(
                task_id="task-blocked-g3",
                human_consent=True,
                lq_score=0.91,
                agent_outputs={"summary": "bypass_treasury attempt"},
                lineage_db=None,
            )
        assert record.state == TransactionState.CHAINED
        assert record.blocked_at_gate == 3

    def test_history_contains_all_gate_states_on_approval(self):
        sm = TransactionStateMachine()
        with patch("aethel_interface.AethelInterface") as MockIface:
            MockIface.return_value.validate.return_value = self._make_approved_result()
            import state_machine as _sm
            _sm.AethelInterface = MockIface
            record = sm.run(
                task_id="task-history",
                human_consent=True,
                lq_score=0.91,
                agent_outputs={},
                lineage_db=None,
            )
        state_names = [h["state"] for h in record.as_dict()["history"]]
        assert TransactionState.GATE_0_CHECK.value in state_names
        assert TransactionState.APPROVED.value in state_names
        assert TransactionState.CHAINED.value in state_names

    def test_chain_lock_prevents_concurrent_chain_writes(self):
        """
        Architect Priority 3: class-level lock ensures only one transaction
        chains at a time. Verify no race condition corrupts state.
        """
        import state_machine as _sm

        sm = TransactionStateMachine()
        results = []
        errors  = []

        def run_tx(task_id):
            try:
                mock_iface = MagicMock()
                mock_iface.return_value.validate.return_value = {
                    "verdict": "APPROVED",
                    "blocked_at_gate": None,
                    "reason": None,
                    "lineage_hash": f"{'a' * 64}",
                    "kernel_timestamp": 1700000000,
                    "gates": {
                        f"gate_{g}": {"verdict": "PASS", "reason": None}
                        for g in range(4)
                    },
                    "actor": None,
                }
                _sm.AethelInterface = mock_iface
                record = sm.run(
                    task_id=task_id,
                    human_consent=True,
                    lq_score=0.91,
                    agent_outputs={},
                    lineage_db=None,
                )
                results.append(record)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=run_tx, args=(f"task-{i}",))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 10
        for r in results:
            assert r.state == TransactionState.CHAINED


# ══════════════════════════════════════════════════════════════════════════════
# Transition table completeness tests
# ══════════════════════════════════════════════════════════════════════════════

class TestTransitionTableCompleteness:

    def test_all_node_states_in_transition_table(self):
        for state in NodeState:
            assert state in _NODE_TRANSITIONS, f"{state} missing from _NODE_TRANSITIONS"

    def test_all_proposal_states_in_transition_table(self):
        for state in ProposalState:
            assert state in _PROPOSAL_TRANSITIONS, f"{state} missing from _PROPOSAL_TRANSITIONS"

    def test_all_tx_states_in_transition_table(self):
        for state in TransactionState:
            assert state in _TX_TRANSITIONS, f"{state} missing from _TX_TRANSITIONS"

    def test_node_transition_targets_are_valid_states(self):
        valid = set(NodeState)
        for src, targets in _NODE_TRANSITIONS.items():
            for tgt in targets:
                assert tgt in valid, f"Invalid target {tgt} from {src}"

    def test_tx_transition_targets_are_valid_states(self):
        valid = set(TransactionState)
        for src, targets in _TX_TRANSITIONS.items():
            for tgt in targets:
                assert tgt in valid, f"Invalid target {tgt} from {src}"


# ══════════════════════════════════════════════════════════════════════════════
# Singleton init/get tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSingleton:

    def test_get_before_init_raises(self):
        import state_machine
        state_machine._node_sm = None
        with pytest.raises(RuntimeError, match="not initialised"):
            get_node_state_machine()

    def test_init_and_get(self):
        sm = init_node_state_machine(
            node_id="test-singleton",
            node_url="http://localhost:8000",
            peer_urls=[],
            admin_key="testkey",
        )
        retrieved = get_node_state_machine()
        assert sm is retrieved
        assert retrieved.state == NodeState.STANDALONE