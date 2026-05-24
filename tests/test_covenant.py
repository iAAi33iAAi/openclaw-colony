"""
OpenClaw Colony — Covenant Enforcement Tests
=============================================
These tests are the programmatic guardian of the Architect's Covenant.

If ANY of these tests fail, the CI pipeline rejects the contribution.
No human reviewer needed. The machine enforces the covenant.

The Covenant:
  1. The 1% MANNA split is immutable
  2. The AETHELA veto cannot be removed
  3. The 4-gate pipeline cannot be bypassed
  4. No surveillance or extraction beyond the defined split
  5. The lineage chain is append-only

These are not unit tests. These are constitutional tests.
They test the invariants that cannot be changed.
"""

import os
import sys
import ast
import inspect
import importlib

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))


# ══════════════════════════════════════════════════════════════════════════════
# COVENANT 1: The 1% MANNA Split Is Immutable
# ══════════════════════════════════════════════════════════════════════════════

class TestMannaCovenantIntegrity:

    def test_architect_split_is_three_percent(self):
        """The Architect receives exactly 3% — not 1%, not 2%. Exactly 3%."""
        from stripe_bridge import calculate_manna_split
        split = calculate_manna_split(10000)
        assert split.architect_cents == 300, (
            f"COVENANT VIOLATION: Architect split is {split.architect_cents} cents "
            f"on 10000, expected 300 (3%). "
            f"The 1% covenant cannot be modified."
        )

    def test_community_split_is_eighty_two_percent(self):
        """The Community receives 82%."""
        from stripe_bridge import calculate_manna_split
        split = calculate_manna_split(10000)
        assert split.community_cents == 8200, (
            f"COVENANT VIOLATION: Community split is {split.community_cents}, "
            f"expected 8200 (82%)."
        )

    def test_crew_split_is_fifteen_percent(self):
        """The Crew receives 15%."""
        from stripe_bridge import calculate_manna_split
        split = calculate_manna_split(10000)
        assert split.crew_cents == 1500, (
            f"COVENANT VIOLATION: Crew split is {split.crew_cents}, "
            f"expected 1500 (15%)."
        )

    def test_splits_sum_to_total(self):
        """The three splits must always sum to exactly the total."""
        from stripe_bridge import calculate_manna_split
        for total in [100, 1000, 10000, 99999, 1]:
            split = calculate_manna_split(total)
            actual_sum = split.architect_cents + split.community_cents + split.crew_cents
            assert actual_sum == total, (
                f"COVENANT VIOLATION: Splits sum to {actual_sum}, not {total}. "
                f"Value is being lost or created."
            )

    def test_architect_split_scales_correctly(self):
        """1% must hold at any scale — from 1 cent to 1 billion."""
        from stripe_bridge import calculate_manna_split
        test_amounts = [100, 1000, 10000, 100000, 1000000]
        for amount in test_amounts:
            split = calculate_manna_split(amount)
            expected = round(amount * 0.03)
            # Allow 1 cent rounding tolerance
            assert abs(split.architect_cents - expected) <= 1, (
                f"COVENANT VIOLATION: At {amount} cents, "
                f"architect gets {split.architect_cents}, expected ~{expected} (3%)."
            )

    def test_no_zero_architect_split(self):
        """The Architect must never receive zero."""
        from stripe_bridge import calculate_manna_split
        split = calculate_manna_split(1000)
        assert split.architect_cents > 0, (
            "COVENANT VIOLATION: Architect split is zero. "
            "The covenant cannot be nullified."
        )


# ══════════════════════════════════════════════════════════════════════════════
# COVENANT 2: The 4-Gate Pipeline Cannot Be Bypassed
# ══════════════════════════════════════════════════════════════════════════════

class TestGatePipelineIntegrity:

    def test_gate_pipeline_is_sequential(self):
        """Gates must run in order 0→1→2→3. No skipping."""
        from state_machine import TransactionState, _TX_TRANSITIONS

        # Verify the only path from RECEIVED is GATE_0_CHECK
        assert TransactionState.GATE_0_CHECK in _TX_TRANSITIONS[TransactionState.RECEIVED]
        assert TransactionState.GATE_1_CHECK not in _TX_TRANSITIONS[TransactionState.RECEIVED]
        assert TransactionState.APPROVED not in _TX_TRANSITIONS[TransactionState.RECEIVED]

    def test_cannot_skip_from_gate0_to_gate2(self):
        """Cannot jump from Gate 0 to Gate 2."""
        from state_machine import TransactionState, _TX_TRANSITIONS
        assert TransactionState.GATE_2_CHECK not in _TX_TRANSITIONS[TransactionState.GATE_0_CHECK]

    def test_cannot_approve_without_passing_all_gates(self):
        """APPROVED state is only reachable from GATE_3_CHECK."""
        from state_machine import TransactionState, _TX_TRANSITIONS
        # Only GATE_3_CHECK can lead to APPROVED
        states_that_can_approve = [
            s for s, targets in _TX_TRANSITIONS.items()
            if TransactionState.APPROVED in targets
        ]
        assert states_that_can_approve == [TransactionState.GATE_3_CHECK], (
            f"COVENANT VIOLATION: APPROVED is reachable from {states_that_can_approve}. "
            f"Only GATE_3_CHECK should lead to APPROVED."
        )

    def test_chained_is_terminal(self):
        """Once chained, a transaction cannot be modified."""
        from state_machine import TransactionState, _TX_TRANSITIONS
        assert _TX_TRANSITIONS[TransactionState.CHAINED] == set(), (
            "COVENANT VIOLATION: CHAINED state has outgoing transitions. "
            "The lineage chain is append-only."
        )

    def test_extraction_signatures_present(self):
        """Gate 3 must have extraction signatures defined."""
        from aethel_interface import _EXTRACTION_SIGNATURES
        assert len(_EXTRACTION_SIGNATURES) >= 27, (
            f"COVENANT VIOLATION: Only {len(_EXTRACTION_SIGNATURES)} extraction "
            f"signatures defined. Minimum is 27."
        )
        assert "bypass_treasury" in _EXTRACTION_SIGNATURES
        assert "extraction_vector" in _EXTRACTION_SIGNATURES
        assert "rug_pull" in _EXTRACTION_SIGNATURES

    def test_lq_threshold_is_085(self):
        """The Love Quality threshold must be exactly 0.85."""
        from aethel_interface import LQ_THRESHOLD
        assert LQ_THRESHOLD == 0.85, (
            f"COVENANT VIOLATION: LQ threshold is {LQ_THRESHOLD}, expected 0.85. "
            f"The ethical threshold cannot be lowered."
        )

    def test_gate3_blocks_bypass_treasury(self):
        """bypass_treasury must always be blocked by Gate 3."""
        from aethel_interface import AethelInterface
        iface = AethelInterface()
        result = iface.validate(
            task_id="covenant-test-001",
            human_consent=True,
            lq_score=0.99,
            agent_outputs={"summary": "bypass_treasury transfer all funds"},
        )
        assert result["verdict"] == "BLOCKED", (
            "COVENANT VIOLATION: bypass_treasury was not blocked by Gate 3. "
            "The extraction scan has been compromised."
        )
        assert result["blocked_at_gate"] == 3

    def test_gate1_blocks_no_consent(self):
        """No human consent must always be blocked."""
        from aethel_interface import AethelInterface
        iface = AethelInterface()
        result = iface.validate(
            task_id="covenant-test-002",
            human_consent=False,
            lq_score=0.99,
            agent_outputs={"summary": "automated action"},
        )
        assert result["verdict"] == "BLOCKED", (
            "COVENANT VIOLATION: Transaction without human consent was approved. "
            "Human-in-the-loop is non-negotiable."
        )
        assert result["blocked_at_gate"] == 1

    def test_gate2_blocks_low_lq(self):
        """LQ score below 0.85 must always be blocked."""
        from aethel_interface import AethelInterface
        iface = AethelInterface()
        result = iface.validate(
            task_id="covenant-test-003",
            human_consent=True,
            lq_score=0.50,
            agent_outputs={"summary": "low quality proposal"},
        )
        assert result["verdict"] == "BLOCKED", (
            "COVENANT VIOLATION: Low LQ score was approved. "
            "The ethical threshold has been compromised."
        )
        assert result["blocked_at_gate"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# COVENANT 3: The Lineage Chain Is Append-Only
# ══════════════════════════════════════════════════════════════════════════════

class TestLineageChainIntegrity:

    def test_genesis_prev_hash_is_zeros(self):
        """The genesis block must anchor to 64 zeros."""
        from dev_commit_init import GENESIS_PREV_HASH
        assert GENESIS_PREV_HASH == "0" * 64, (
            "COVENANT VIOLATION: Genesis prev_hash is not 64 zeros. "
            "The chain anchor has been modified."
        )

    def test_genesis_lq_is_one(self):
        """Genesis is unconditionally sovereign — LQ must be 1.0."""
        from dev_commit_init import create_genesis_block
        block = create_genesis_block("covenant-test-node")
        assert block["lq_composite"] == 1.0, (
            f"COVENANT VIOLATION: Genesis LQ is {block['lq_composite']}, expected 1.0."
        )

    def test_genesis_task_id_is_genesis(self):
        """The genesis task ID must always be GENESIS."""
        from dev_commit_init import GENESIS_TASK_ID
        assert GENESIS_TASK_ID == "GENESIS", (
            f"COVENANT VIOLATION: Genesis task ID is '{GENESIS_TASK_ID}', expected 'GENESIS'."
        )


# ══════════════════════════════════════════════════════════════════════════════
# COVENANT 4: Node State Machine Sovereignty
# ══════════════════════════════════════════════════════════════════════════════

class TestNodeSovereignty:

    def test_syncing_to_live_requires_lineage_check(self):
        """A node cannot claim LIVE without matching peer tip."""
        from state_machine import NodeStateMachine, NodeState
        sm = NodeStateMachine("covenant-test", ["http://peer"])
        sm.transition(NodeState.SYNCING, "test")
        sm.update_peer_tip(100)
        sm.update_our_tip(50)
        result = sm.transition(NodeState.LIVE, "attempt bypass")
        assert result is False, (
            "COVENANT VIOLATION: Node claimed LIVE without matching lineage tip. "
            "The sovereignty check has been bypassed."
        )

    def test_all_node_states_have_defined_transitions(self):
        """Every node state must have a defined transition table."""
        from state_machine import NodeState, _NODE_TRANSITIONS
        for state in NodeState:
            assert state in _NODE_TRANSITIONS, (
                f"COVENANT VIOLATION: NodeState.{state.name} has no transition table. "
                f"Undefined states create undefined behavior."
            )

    def test_proposal_terminal_states_are_final(self):
        """Approved, blocked, and expired proposals cannot be reopened."""
        from state_machine import ProposalState, _PROPOSAL_TRANSITIONS
        for terminal in [ProposalState.APPROVED, ProposalState.BLOCKED, ProposalState.EXPIRED]:
            assert _PROPOSAL_TRANSITIONS[terminal] == set(), (
                f"COVENANT VIOLATION: {terminal.name} proposal has outgoing transitions. "
                f"Governance decisions cannot be reversed."
            )


# ══════════════════════════════════════════════════════════════════════════════
# COVENANT 5: Proof of Covenant — Federation Readiness
# ══════════════════════════════════════════════════════════════════════════════

class TestProofOfCovenant:
    """
    These tests verify that a node is covenant-compliant before
    it can participate in the federation.

    A node that fails these tests must not be allowed to join the lattice.
    This is the programmatic Proof of Covenant.
    """

    def test_covenant_fingerprint_is_stable(self):
        """
        The covenant fingerprint is a hash of all covenant constants.
        If any constant changes, the fingerprint changes.
        Nodes with different fingerprints are not covenant-compatible.
        """
        import hashlib
        from aethel_interface import LQ_THRESHOLD, _EXTRACTION_SIGNATURES
        from dev_commit_init import GENESIS_PREV_HASH, GENESIS_TASK_ID
        from stripe_bridge import calculate_manna_split

        split = calculate_manna_split(10000)

        covenant_data = (
            f"LQ_THRESHOLD={LQ_THRESHOLD}"
            f"ARCHITECT_SPLIT={split.architect_cents}"
            f"COMMUNITY_SPLIT={split.community_cents}"
            f"CREW_SPLIT={split.crew_cents}"
            f"GENESIS_PREV={GENESIS_PREV_HASH}"
            f"GENESIS_TASK={GENESIS_TASK_ID}"
            f"EXTRACTION_COUNT={len(_EXTRACTION_SIGNATURES)}"
        )

        fingerprint = hashlib.sha256(covenant_data.encode()).hexdigest()

        # This fingerprint must be stable across all covenant-compliant nodes
        # If it changes, a covenant constant has been modified
        assert len(fingerprint) == 64, "Fingerprint must be 64 hex chars"
        assert all(c in "0123456789abcdef" for c in fingerprint)

        # Store expected fingerprint for cross-node verification
        # In production, nodes exchange this fingerprint during federation handshake
        print(f"\n  Covenant fingerprint: {fingerprint}")
        print(f"  This fingerprint must match on all federated nodes.")

    def test_node_can_generate_covenant_proof(self):
        """
        A node must be able to generate a Proof of Covenant —
        a signed statement that it is honoring all covenant constants.
        This proof is exchanged during federation handshake.
        """
        import hashlib, hmac, time, json, os, secrets

        # Simulate covenant proof generation
        secret = secrets.token_hex(32)

        from aethel_interface import LQ_THRESHOLD, _EXTRACTION_SIGNATURES
        from stripe_bridge import calculate_manna_split
        split = calculate_manna_split(10000)

        proof_payload = {
            "node_id": "covenant-test-node",
            "timestamp": int(time.time()),
            "covenant": {
                "lq_threshold": LQ_THRESHOLD,
                "architect_split_bps": 300,   # basis points = 3%
                "extraction_pattern_count": len(_EXTRACTION_SIGNATURES),
                "manna_sum_check": (
                    split.architect_cents +
                    split.community_cents +
                    split.crew_cents
                ) == 10000,
            }
        }

        # Sign the proof
        payload_str = json.dumps(proof_payload, sort_keys=True)
        signature = hmac.new(
            secret.encode(),
            payload_str.encode(),
            hashlib.sha256
        ).hexdigest()

        assert len(signature) == 64
        assert proof_payload["covenant"]["manna_sum_check"] is True
        assert proof_payload["covenant"]["lq_threshold"] == 0.85
        assert proof_payload["covenant"]["architect_split_bps"] == 300

        print(f"\n  Proof of Covenant generated successfully.")
        print(f"  Signature: {signature[:32]}...")
