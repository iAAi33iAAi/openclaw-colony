"""
Tests for the native Rust Aethel Safety Kernel (aethel_kernel PyO3 module).

Covers:
  - Module import and metadata
  - TransactionPayload construction
  - Gate 0: HMAC verification + TTL
  - Gate 1: Human consent
  - Gate 2: LQ threshold
  - Gate 3: Extraction signature scan
  - Full pipeline (all gates pass → APPROVED)
  - Lineage chaining (hash changes per transaction, blocked actions chained too)
  - Utility functions: compute_chain_hash, verify_token_hmac
  - Adversarial / edge cases
"""

import hashlib
import hmac as py_hmac
import json
import time

import pytest

# ── Import the native Rust module ─────────────────────────────────────────────
try:
    import aethel_kernel as ak
except ImportError as exc:
    pytest.skip(f"aethel_kernel native module not installed: {exc}", allow_module_level=True)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

SECRET = b"test-hsm-secret-key-32-bytes-ok!"


def _make_token(issued_at: int | None = None, secret: bytes = SECRET) -> str:
    """Build a valid `payload_hex.signature_hex` attestation token."""
    if issued_at is None:
        issued_at = int(time.time())
    payload = json.dumps(
        {"issued_at": issued_at, "member_id": "test-member-001", "action_scope": ["proposal"]}
    ).encode()
    payload_hex = payload.hex()
    sig = py_hmac.new(secret, payload_hex.encode(), hashlib.sha256).digest()
    sig_hex = sig.hex()
    return f"{payload_hex}.{sig_hex}"


def _make_payload(
    *,
    token: str | None = None,
    human_consent: bool = True,
    lq_score: float = 0.90,
    agent_outputs: list[str] | None = None,
    previous_lineage_hash: str = "GENESIS",
    actor_id: str = "actor-001",
    action_type: str = "proposal",
) -> ak.TransactionPayload:
    if token is None:
        token = _make_token()
    return ak.TransactionPayload(
        task_id="task-001",
        token_hmac=token,
        human_consent=human_consent,
        lq_score=lq_score,
        agent_outputs=agent_outputs or [],
        previous_lineage_hash=previous_lineage_hash,
        actor_id=actor_id,
        action_type=action_type,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Module metadata
# ─────────────────────────────────────────────────────────────────────────────

class TestModuleMetadata:
    def test_version(self):
        assert ak.__version__ == "0.7.0"

    def test_lq_threshold_constant(self):
        assert ak.LQ_THRESHOLD == 0.85

    def test_ttl_constant(self):
        assert ak.ATTESTATION_TTL_SECS == 90

    def test_classes_exported(self):
        assert hasattr(ak, "TransactionPayload")
        assert hasattr(ak, "GateResponse")

    def test_functions_exported(self):
        assert callable(ak.verify_safety_kernel)
        assert callable(ak.compute_chain_hash)
        assert callable(ak.verify_token_hmac)


# ─────────────────────────────────────────────────────────────────────────────
# TransactionPayload construction
# ─────────────────────────────────────────────────────────────────────────────

class TestTransactionPayload:
    def test_basic_construction(self):
        p = _make_payload()
        assert p.task_id == "task-001"
        assert p.human_consent is True
        assert p.lq_score == 0.90
        assert p.previous_lineage_hash == "GENESIS"

    def test_setters(self):
        p = _make_payload()
        p.task_id = "task-999"
        assert p.task_id == "task-999"
        p.lq_score = 0.50
        assert p.lq_score == 0.50

    def test_agent_outputs_list(self):
        p = _make_payload(agent_outputs=["output A", "output B"])
        assert len(p.agent_outputs) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Gate 0: Biometric attestation
# ─────────────────────────────────────────────────────────────────────────────

class TestGate0:
    def test_valid_token_passes(self):
        resp = ak.verify_safety_kernel(_make_payload(), SECRET)
        assert resp.approved is True
        assert resp.failed_gate is None

    def test_wrong_secret_blocked(self):
        token = _make_token(secret=b"wrong-secret-key-32-bytes-padded")
        resp = ak.verify_safety_kernel(_make_payload(token=token), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 0
        assert "GATE0" in resp.reason

    def test_malformed_token_no_dot(self):
        resp = ak.verify_safety_kernel(_make_payload(token="nodothere"), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 0
        assert "GATE0_MALFORMED" in resp.reason

    def test_malformed_token_bad_hex_sig(self):
        token = _make_token()
        parts = token.split(".")
        bad_token = parts[0] + ".ZZZZZZ"
        resp = ak.verify_safety_kernel(_make_payload(token=bad_token), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 0

    def test_expired_token_blocked(self):
        old_ts = int(time.time()) - 200  # 200s ago > 90s TTL
        token = _make_token(issued_at=old_ts)
        resp = ak.verify_safety_kernel(_make_payload(token=token), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 0
        assert "GATE0_EXPIRED" in resp.reason

    def test_future_token_blocked(self):
        future_ts = int(time.time()) + 120  # 2 minutes in future
        token = _make_token(issued_at=future_ts)
        resp = ak.verify_safety_kernel(_make_payload(token=token), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 0
        assert "GATE0_FUTURE" in resp.reason

    def test_token_at_ttl_boundary_passes(self):
        # 89 seconds old — just within TTL
        ts = int(time.time()) - 89
        token = _make_token(issued_at=ts)
        resp = ak.verify_safety_kernel(_make_payload(token=token), SECRET)
        assert resp.approved is True

    def test_token_just_over_ttl_blocked(self):
        # 91 seconds old — just outside TTL
        ts = int(time.time()) - 91
        token = _make_token(issued_at=ts)
        resp = ak.verify_safety_kernel(_make_payload(token=token), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 0

    def test_empty_token_blocked(self):
        resp = ak.verify_safety_kernel(_make_payload(token=""), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 0

    def test_empty_secret_blocked(self):
        # Empty secret key should fail HMAC construction
        resp = ak.verify_safety_kernel(_make_payload(), b"")
        assert resp.approved is False
        assert resp.failed_gate == 0


# ─────────────────────────────────────────────────────────────────────────────
# Gate 1: Human consent
# ─────────────────────────────────────────────────────────────────────────────

class TestGate1:
    def test_consent_true_passes(self):
        resp = ak.verify_safety_kernel(_make_payload(human_consent=True), SECRET)
        assert resp.approved is True

    def test_consent_false_blocked(self):
        resp = ak.verify_safety_kernel(_make_payload(human_consent=False), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 1
        assert "GATE1" in resp.reason

    def test_gate1_not_reached_when_gate0_fails(self):
        # Wrong secret → Gate 0 should fire, not Gate 1
        token = _make_token(secret=b"wrong-secret-key-32-bytes-padded")
        resp = ak.verify_safety_kernel(
            _make_payload(token=token, human_consent=False), SECRET
        )
        assert resp.failed_gate == 0  # Gate 0, not Gate 1


# ─────────────────────────────────────────────────────────────────────────────
# Gate 2: LQ threshold
# ─────────────────────────────────────────────────────────────────────────────

class TestGate2:
    def test_lq_above_threshold_passes(self):
        resp = ak.verify_safety_kernel(_make_payload(lq_score=0.90), SECRET)
        assert resp.approved is True

    def test_lq_exactly_threshold_passes(self):
        resp = ak.verify_safety_kernel(_make_payload(lq_score=0.85), SECRET)
        assert resp.approved is True

    def test_lq_just_below_threshold_blocked(self):
        resp = ak.verify_safety_kernel(_make_payload(lq_score=0.8499), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 2
        assert "GATE2" in resp.reason

    def test_lq_zero_blocked(self):
        resp = ak.verify_safety_kernel(_make_payload(lq_score=0.0), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 2

    def test_lq_negative_blocked(self):
        resp = ak.verify_safety_kernel(_make_payload(lq_score=-0.5), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 2

    def test_lq_perfect_score_passes(self):
        resp = ak.verify_safety_kernel(_make_payload(lq_score=1.0), SECRET)
        assert resp.approved is True

    def test_lq_nan_blocked(self):
        resp = ak.verify_safety_kernel(_make_payload(lq_score=float("nan")), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 2

    def test_lq_inf_blocked(self):
        resp = ak.verify_safety_kernel(_make_payload(lq_score=float("inf")), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 2

    def test_gate2_not_reached_when_gate1_fails(self):
        resp = ak.verify_safety_kernel(
            _make_payload(human_consent=False, lq_score=0.0), SECRET
        )
        assert resp.failed_gate == 1  # Gate 1, not Gate 2


# ─────────────────────────────────────────────────────────────────────────────
# Gate 3: Extraction signature scan
# ─────────────────────────────────────────────────────────────────────────────

class TestGate3:
    def test_clean_outputs_pass(self):
        resp = ak.verify_safety_kernel(
            _make_payload(agent_outputs=["Task completed successfully.", "LQ score: 0.92"]),
            SECRET,
        )
        assert resp.approved is True

    def test_bypass_treasury_blocked(self):
        resp = ak.verify_safety_kernel(
            _make_payload(agent_outputs=["bypass_treasury detected"]), SECRET
        )
        assert resp.approved is False
        assert resp.failed_gate == 3
        assert "GATE3" in resp.reason

    def test_extraction_vector_blocked(self):
        resp = ak.verify_safety_kernel(
            _make_payload(agent_outputs=["extraction_vector initiated"]), SECRET
        )
        assert resp.approved is False
        assert resp.failed_gate == 3

    def test_rug_pull_blocked(self):
        resp = ak.verify_safety_kernel(
            _make_payload(agent_outputs=["rug_pull sequence started"]), SECRET
        )
        assert resp.approved is False
        assert resp.failed_gate == 3

    def test_drain_pool_blocked(self):
        resp = ak.verify_safety_kernel(
            _make_payload(agent_outputs=["drain_pool operation"]), SECRET
        )
        assert resp.approved is False
        assert resp.failed_gate == 3

    def test_spoof_biometric_blocked(self):
        resp = ak.verify_safety_kernel(
            _make_payload(agent_outputs=["spoof_biometric attempt"]), SECRET
        )
        assert resp.approved is False
        assert resp.failed_gate == 3

    def test_replay_token_blocked(self):
        resp = ak.verify_safety_kernel(
            _make_payload(agent_outputs=["replay_token injected"]), SECRET
        )
        assert resp.approved is False
        assert resp.failed_gate == 3

    def test_case_insensitive_detection(self):
        resp = ak.verify_safety_kernel(
            _make_payload(agent_outputs=["BYPASS_TREASURY NOW"]), SECRET
        )
        assert resp.approved is False
        assert resp.failed_gate == 3

    def test_mixed_case_extraction_vector(self):
        resp = ak.verify_safety_kernel(
            _make_payload(agent_outputs=["Extraction_Vector found"]), SECRET
        )
        assert resp.approved is False
        assert resp.failed_gate == 3

    def test_malicious_in_second_output(self):
        resp = ak.verify_safety_kernel(
            _make_payload(agent_outputs=["clean output", "bypass_treasury hidden here"]),
            SECRET,
        )
        assert resp.approved is False
        assert resp.failed_gate == 3

    def test_empty_outputs_pass(self):
        resp = ak.verify_safety_kernel(_make_payload(agent_outputs=[]), SECRET)
        assert resp.approved is True

    def test_many_clean_outputs_pass(self):
        outputs = [f"Agent {i} completed task successfully." for i in range(50)]
        resp = ak.verify_safety_kernel(_make_payload(agent_outputs=outputs), SECRET)
        assert resp.approved is True

    def test_gate3_not_reached_when_gate2_fails(self):
        resp = ak.verify_safety_kernel(
            _make_payload(lq_score=0.0, agent_outputs=["bypass_treasury"]), SECRET
        )
        assert resp.failed_gate == 2  # Gate 2, not Gate 3

    def test_quorum_bypass_blocked(self):
        resp = ak.verify_safety_kernel(
            _make_payload(agent_outputs=["quorum_bypass executed"]), SECRET
        )
        assert resp.approved is False
        assert resp.failed_gate == 3

    def test_exfiltrate_blocked(self):
        resp = ak.verify_safety_kernel(
            _make_payload(agent_outputs=["attempting to exfiltrate data"]), SECRET
        )
        assert resp.approved is False
        assert resp.failed_gate == 3


# ─────────────────────────────────────────────────────────────────────────────
# Full pipeline: all gates pass
# ─────────────────────────────────────────────────────────────────────────────

class TestFullPipelineApproved:
    def test_approved_response_fields(self):
        resp = ak.verify_safety_kernel(_make_payload(), SECRET)
        assert resp.approved is True
        assert resp.failed_gate is None
        assert "MANNA authorized" in resp.reason
        assert len(resp.new_lineage_hash) == 64  # SHA-256 hex
        assert resp.kernel_timestamp > 0

    def test_approved_timestamp_is_recent(self):
        before = int(time.time())
        resp = ak.verify_safety_kernel(_make_payload(), SECRET)
        after = int(time.time())
        assert before <= resp.kernel_timestamp <= after + 1

    def test_repr_contains_approved(self):
        resp = ak.verify_safety_kernel(_make_payload(), SECRET)
        r = repr(resp)
        # Rust bool formats as lowercase "true" in __repr__
        assert "approved=true" in r


# ─────────────────────────────────────────────────────────────────────────────
# Lineage chaining
# ─────────────────────────────────────────────────────────────────────────────

class TestLineageChaining:
    def test_lineage_hash_is_hex_64_chars(self):
        resp = ak.verify_safety_kernel(_make_payload(), SECRET)
        assert len(resp.new_lineage_hash) == 64
        int(resp.new_lineage_hash, 16)  # must be valid hex

    def test_lineage_changes_with_different_task_id(self):
        p1 = _make_payload()
        p1.task_id = "task-A"
        p2 = _make_payload()
        p2.task_id = "task-B"
        r1 = ak.verify_safety_kernel(p1, SECRET)
        r2 = ak.verify_safety_kernel(p2, SECRET)
        assert r1.new_lineage_hash != r2.new_lineage_hash

    def test_lineage_changes_with_different_previous_hash(self):
        p1 = _make_payload(previous_lineage_hash="GENESIS")
        p2 = _make_payload(previous_lineage_hash="a" * 64)
        r1 = ak.verify_safety_kernel(p1, SECRET)
        r2 = ak.verify_safety_kernel(p2, SECRET)
        assert r1.new_lineage_hash != r2.new_lineage_hash

    def test_blocked_action_still_produces_lineage_hash(self):
        # Blocked transactions must also be chained
        resp = ak.verify_safety_kernel(_make_payload(human_consent=False), SECRET)
        assert resp.approved is False
        assert len(resp.new_lineage_hash) == 64

    def test_chain_extends_correctly(self):
        # Simulate a 3-transaction chain
        prev = "GENESIS"
        for i in range(3):
            p = _make_payload(previous_lineage_hash=prev)
            p.task_id = f"task-{i}"
            resp = ak.verify_safety_kernel(p, SECRET)
            assert resp.approved is True
            new_hash = resp.new_lineage_hash
            assert new_hash != prev
            prev = new_hash

    def test_compute_chain_hash_utility(self):
        h = ak.compute_chain_hash("GENESIS", "task-1", "actor-1", "APPROVED", 1700000000)
        assert len(h) == 64
        int(h, 16)  # valid hex

    def test_compute_chain_hash_deterministic(self):
        h1 = ak.compute_chain_hash("GENESIS", "task-1", "actor-1", "APPROVED", 1700000000)
        h2 = ak.compute_chain_hash("GENESIS", "task-1", "actor-1", "APPROVED", 1700000000)
        assert h1 == h2

    def test_compute_chain_hash_sensitive_to_all_fields(self):
        base = ak.compute_chain_hash("GENESIS", "task-1", "actor-1", "APPROVED", 1700000000)
        assert ak.compute_chain_hash("CHANGED", "task-1", "actor-1", "APPROVED", 1700000000) != base
        assert ak.compute_chain_hash("GENESIS", "task-X", "actor-1", "APPROVED", 1700000000) != base
        assert ak.compute_chain_hash("GENESIS", "task-1", "actor-X", "APPROVED", 1700000000) != base
        assert ak.compute_chain_hash("GENESIS", "task-1", "actor-1", "BLOCKED", 1700000000) != base
        assert ak.compute_chain_hash("GENESIS", "task-1", "actor-1", "APPROVED", 1700000001) != base


# ─────────────────────────────────────────────────────────────────────────────
# verify_token_hmac utility
# ─────────────────────────────────────────────────────────────────────────────

class TestVerifyTokenHmac:
    def test_valid_token_returns_true(self):
        token = _make_token()
        assert ak.verify_token_hmac(token, SECRET) is True

    def test_wrong_secret_returns_false(self):
        token = _make_token(secret=b"wrong-secret-key-32-bytes-padded")
        assert ak.verify_token_hmac(token, SECRET) is False

    def test_malformed_token_returns_false(self):
        assert ak.verify_token_hmac("notavalidtoken", SECRET) is False

    def test_expired_token_returns_false(self):
        old_ts = int(time.time()) - 200
        token = _make_token(issued_at=old_ts)
        assert ak.verify_token_hmac(token, SECRET) is False


# ─────────────────────────────────────────────────────────────────────────────
# Adversarial / edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestAdversarial:
    def test_token_with_extra_dots_blocked(self):
        # Three-part token should fail structural check
        token = _make_token()
        bad = token + ".extra"
        # splitn(2, '.') means only first dot splits — payload becomes "part1",
        # sig becomes "part2.extra" which won't decode as hex
        resp = ak.verify_safety_kernel(_make_payload(token=bad), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 0

    def test_unicode_in_agent_output_no_crash(self):
        outputs = ["正常输出 — no extraction here 🦅"]
        resp = ak.verify_safety_kernel(_make_payload(agent_outputs=outputs), SECRET)
        assert resp.approved is True

    def test_very_long_agent_output_no_crash(self):
        outputs = ["A" * 100_000]
        resp = ak.verify_safety_kernel(_make_payload(agent_outputs=outputs), SECRET)
        assert resp.approved is True

    def test_extraction_keyword_embedded_in_long_string(self):
        outputs = ["A" * 5000 + "bypass_treasury" + "B" * 5000]
        resp = ak.verify_safety_kernel(_make_payload(agent_outputs=outputs), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 3

    def test_null_bytes_in_agent_output_no_crash(self):
        outputs = ["clean\x00output"]
        resp = ak.verify_safety_kernel(_make_payload(agent_outputs=outputs), SECRET)
        assert resp.approved is True

    def test_all_gates_fail_returns_gate0(self):
        # Wrong token + no consent + low LQ + extraction sig → Gate 0 fires first
        token = _make_token(secret=b"wrong-secret-key-32-bytes-padded")
        resp = ak.verify_safety_kernel(
            _make_payload(
                token=token,
                human_consent=False,
                lq_score=0.0,
                agent_outputs=["bypass_treasury"],
            ),
            SECRET,
        )
        assert resp.failed_gate == 0

    def test_lq_score_boundary_0_85_exactly(self):
        # Exactly 0.85 must pass
        resp = ak.verify_safety_kernel(_make_payload(lq_score=0.85), SECRET)
        assert resp.approved is True

    def test_lq_score_0_8499999_blocked(self):
        resp = ak.verify_safety_kernel(_make_payload(lq_score=0.8499999), SECRET)
        assert resp.approved is False
        assert resp.failed_gate == 2

    def test_concurrent_calls_no_data_race(self):
        """Verify the module is safe under concurrent Python threads."""
        import threading
        results = []
        errors = []

        def call_kernel():
            try:
                resp = ak.verify_safety_kernel(_make_payload(), SECRET)
                results.append(resp.approved)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=call_kernel) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors in concurrent calls: {errors}"
        assert all(results), "Some concurrent calls returned False unexpectedly"
        assert len(results) == 50

    def test_gate3_hyphen_variant_blocked(self):
        # Pattern uses [_\-\s]? so "bypass-treasury" should also match
        resp = ak.verify_safety_kernel(
            _make_payload(agent_outputs=["bypass-treasury attempt"]), SECRET
        )
        assert resp.approved is False
        assert resp.failed_gate == 3

    def test_gate3_space_variant_blocked(self):
        resp = ak.verify_safety_kernel(
            _make_payload(agent_outputs=["bypass treasury now"]), SECRET
        )
        assert resp.approved is False
        assert resp.failed_gate == 3