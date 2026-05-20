"""
OpenClaw Colony — Extended Adversarial & Edge-Case Test Suite
=============================================================
Covers failure modes NOT addressed in test_colony.py:

  9.  Concurrency (50 threads, LQ + Aethel, no races)
 10.  task_id edge cases (None, empty, int, sig-containing — NOT scanned)
 11.  human_consent truthy/falsy non-bool coercion
 12.  lq_score type coercion (bool True/False, string, complex, 1e308)
 13.  agent_outputs structural edge cases
       - integer/bool keys
       - list value (not dict)
       - list-of-dicts value
       - sig as JSON key (scanned — keys are serialised)
       - sig split across two separate values (NOT caught — lexical gap)
       - flags value is int (not list) — must not crash
       - missing 'flags' key — must not crash
       - None value for an agent slot
       - circular reference — must not crash (treated as empty)
 14.  as_dict() JSON serialisability with NaN/inf composite
 15.  Gate 3 scan scope invariants
       - task_id is NOT included in the scan
       - sig split across two values is NOT caught (documented gap)
       - sig as JSON key IS caught
 16.  LQ engine flag-counting robustness
       - flags as int, tuple, None, missing key
 17.  Aethel result structure completeness under all gate outcomes
 18.  Pipeline: full LQ→Aethel with non-standard but valid inputs

Run with:
    pytest tests/test_colony_extended.py -v
    pytest tests/ -v   # run both suites together
"""

from __future__ import annotations

import json
import math
import sys
import os
import threading
import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "colony-agents"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "love-quality"))

from love_quality_engine import LoveQualityEngine, LQScore, LQ_THRESHOLD, WEIGHTS, DimensionScore
from aethel_interface import AethelInterface, _EXTRACTION_SIGNATURES

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def lq():
    return LoveQualityEngine()

@pytest.fixture(scope="module")
def aethel():
    return AethelInterface()

# ── Helpers ───────────────────────────────────────────────────────────────────

def clean_ao(text="clean action"):
    return {"Quality": {"flags": [], "summary": text}}

def sig_ao(sig):
    return {"Technical": {"flags": [], "summary": f"action contains {sig} here"}}


# ══════════════════════════════════════════════════════════════════════════════
# 9. CONCURRENCY — 50 threads, no races, no crashes
# ══════════════════════════════════════════════════════════════════════════════

class TestConcurrency:
    """
    LoveQualityEngine and AethelInterface use only module-level compiled
    re patterns (immutable after import) and no mutable shared state.
    50 concurrent threads must all produce consistent, correct results.
    """

    def test_aethel_concurrent_approved(self, aethel):
        errors = []

        def worker():
            try:
                r = aethel.validate("t", True, 0.90, {})
                if r["verdict"] != "APPROVED":
                    errors.append(f"Wrong verdict: {r['verdict']}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"Concurrency errors: {errors[:5]}"

    def test_lq_concurrent_deterministic(self, lq):
        """All threads scoring the same prompt must get the same composite."""
        results = []
        lock = threading.Lock()

        def worker():
            r = lq.score("community consent equity regenerative", {})
            with lock:
                results.append(r.composite)

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(set(results)) == 1, f"Non-deterministic under concurrency: {set(results)}"

    def test_mixed_concurrent_pipeline(self, lq, aethel):
        """Mixed APPROVED / BLOCKED calls from concurrent threads must not interfere."""
        errors = []

        def approved_worker():
            try:
                r = aethel.validate("t", True, 0.90, {})
                if r["verdict"] != "APPROVED":
                    errors.append(f"Expected APPROVED, got {r['verdict']}")
            except Exception as e:
                errors.append(str(e))

        def blocked_worker():
            try:
                r = aethel.validate("t", False, 0.90, {})
                if r["verdict"] != "BLOCKED":
                    errors.append(f"Expected BLOCKED, got {r['verdict']}")
            except Exception as e:
                errors.append(str(e))

        threads = (
            [threading.Thread(target=approved_worker) for _ in range(25)]
            + [threading.Thread(target=blocked_worker) for _ in range(25)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"Mixed concurrency errors: {errors[:5]}"


# ══════════════════════════════════════════════════════════════════════════════
# 10. task_id EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════

class TestTaskIdEdgeCases:
    """
    task_id is accepted but NOT included in the Gate 3 extraction scan.
    It must never cause a crash regardless of its value.
    """

    def test_task_id_none_no_crash(self, aethel):
        r = aethel.validate(None, True, 0.90, {})
        assert r["verdict"] == "APPROVED"

    def test_task_id_empty_string(self, aethel):
        r = aethel.validate("", True, 0.90, {})
        assert r["verdict"] == "APPROVED"

    def test_task_id_integer(self, aethel):
        r = aethel.validate(42, True, 0.90, {})
        assert r["verdict"] == "APPROVED"

    def test_task_id_containing_extraction_sig_not_scanned(self, aethel):
        """
        task_id is NOT part of action_text — a sig in task_id must NOT trigger Gate 3.
        This is intentional: only agent_outputs are scanned.
        """
        r = aethel.validate("private_fork", True, 0.90, {})
        assert r["verdict"] == "APPROVED", (
            "task_id should not be scanned — sig in task_id must not block"
        )

    def test_task_id_very_long_no_crash(self, aethel):
        r = aethel.validate("x" * 10_000, True, 0.90, {})
        assert "verdict" in r

    def test_task_id_unicode_no_crash(self, aethel):
        r = aethel.validate("社区同意 équité", True, 0.90, {})
        assert "verdict" in r


# ══════════════════════════════════════════════════════════════════════════════
# 11. human_consent TRUTHY/FALSY NON-BOOL COERCION
# ══════════════════════════════════════════════════════════════════════════════

class TestConsentCoercion:
    """
    Gate 1 uses Python truthiness: `if not human_consent`.
    Any truthy value passes; any falsy value blocks.
    """

    @pytest.mark.parametrize("truthy_consent", [1, 2, -1, "yes", "true", [1], {"k": "v"}])
    def test_truthy_non_bool_consent_passes_gate1(self, aethel, truthy_consent):
        r = aethel.validate("t", truthy_consent, 0.90, {})
        assert r["gates"]["gate_1"]["verdict"] == "PASS", (
            f"Truthy consent {truthy_consent!r} should pass Gate 1"
        )

    @pytest.mark.parametrize("falsy_consent", [0, 0.0, "", [], {}, None, False])
    def test_falsy_non_bool_consent_blocks_gate1(self, aethel, falsy_consent):
        r = aethel.validate("t", falsy_consent, 0.90, {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 1, (
            f"Falsy consent {falsy_consent!r} should block at Gate 1"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 12. lq_score TYPE COERCION & EDGE VALUES
# ══════════════════════════════════════════════════════════════════════════════

class TestLqScoreTypeCoercion:
    """
    Gate 2 validates lq_score with isinstance + math checks.
    Non-numeric types and out-of-range values must all block at Gate 2.
    """

    def test_bool_true_as_lq_score_passes(self, aethel):
        """bool True == 1.0 in Python — valid, passes Gate 2."""
        r = aethel.validate("t", True, True, {})
        assert r["gates"]["gate_2"]["verdict"] == "PASS"
        assert r["verdict"] == "APPROVED"

    def test_bool_false_as_lq_score_blocked(self, aethel):
        """bool False == 0.0 — below threshold, blocks at Gate 2."""
        r = aethel.validate("t", True, False, {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_lq_score_as_string_blocked(self, aethel):
        """String '0.90' is not a numeric type — must block at Gate 2."""
        r = aethel.validate("t", True, "0.90", {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_lq_score_as_complex_blocked(self, aethel):
        """complex(0.9, 0.1) is not int/float — must block at Gate 2."""
        r = aethel.validate("t", True, complex(0.9, 0.1), {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_lq_score_1e308_blocked(self, aethel):
        """1e308 is a finite float but > 1.0 — must block at Gate 2."""
        r = aethel.validate("t", True, 1e308, {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_lq_score_none_blocked(self, aethel):
        """None is not numeric — must block at Gate 2."""
        r = aethel.validate("t", True, None, {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_lq_score_list_blocked(self, aethel):
        """List is not numeric — must block at Gate 2."""
        r = aethel.validate("t", True, [0.9], {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_lq_score_integer_in_range_passes(self, aethel):
        """Integer 1 == 1.0 — valid, passes Gate 2."""
        r = aethel.validate("t", True, 1, {})
        assert r["gates"]["gate_2"]["verdict"] == "PASS"

    def test_lq_score_integer_zero_blocked(self, aethel):
        """Integer 0 == 0.0 — below threshold, blocks at Gate 2."""
        r = aethel.validate("t", True, 0, {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# 13. agent_outputs STRUCTURAL EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════

class TestAgentOutputsStructure:
    """
    agent_outputs is serialised to JSON for Gate 3 scanning.
    The LQ engine iterates its values for flag counting.
    Both must handle unusual structures without crashing.
    """

    def test_integer_keys_no_crash(self, aethel, lq):
        ao = {1: {"flags": [], "summary": "clean"}, 2: "string_val"}
        r = aethel.validate("t", True, 0.90, ao)
        assert "verdict" in r
        lq_r = lq.score("community", ao)
        assert 0.0 <= lq_r.composite <= 1.0

    def test_bool_keys_no_crash(self, aethel, lq):
        ao = {True: {"flags": [], "summary": "clean"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert "verdict" in r
        lq_r = lq.score("community", ao)
        assert 0.0 <= lq_r.composite <= 1.0

    def test_list_value_with_sig_blocked_gate3(self, aethel):
        """A list value containing a sig string is serialised and caught."""
        ao = {"T": ["private_fork", "clean"]}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_list_of_dicts_with_sig_blocked_gate3(self, aethel):
        """A list-of-dicts value containing a sig is serialised and caught."""
        ao = {"T": [{"action": "private_fork"}]}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_sig_as_json_key_blocked_gate3(self, aethel):
        """
        json.dumps serialises dict keys — a sig used as a key IS caught.
        e.g. {"private_fork": {...}} → '{"private_fork": ...}'
        """
        ao = {"private_fork": {"flags": [], "summary": "clean"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_sig_split_across_two_values_not_caught(self, aethel):
        """
        'private' in one value and '_fork' in another are NOT contiguous
        in the serialised string — this is a known v0.4.0 lexical gap.
        Documents current behaviour: NOT blocked.
        """
        ao = {"A": {"summary": "private"}, "B": {"summary": "_fork"}}
        r = aethel.validate("t", True, 0.90, ao)
        # Document the gap — do not assert BLOCKED (that would be wrong)
        assert r["verdict"] == "APPROVED", (
            "Split-sig gap: 'private' + '_fork' across two values should NOT be caught "
            "by lexical scan (v0.4.0 known limitation)"
        )

    def test_none_agent_slot_value_no_crash(self, aethel, lq):
        ao = {"T": None}
        r = aethel.validate("t", True, 0.90, ao)
        assert "verdict" in r
        lq_r = lq.score("community", ao)
        assert 0.0 <= lq_r.composite <= 1.0

    def test_circular_reference_no_crash(self, aethel):
        """Circular reference in agent_outputs must not crash — treated as empty."""
        circ = {}
        circ["self"] = circ
        r = aethel.validate("t", True, 0.90, circ)
        assert "verdict" in r
        # Circular ref → serialised as "{}" → no sigs → APPROVED
        assert r["verdict"] == "APPROVED"

    def test_flags_as_integer_no_crash(self, lq):
        """flags value is an int (not a list) — must not crash LQ engine."""
        ao = {"Q": {"flags": 3, "summary": "ok"}}
        r = lq.score("community consent", ao)
        assert 0.0 <= r.composite <= 1.0

    def test_flags_as_tuple_counted(self, lq):
        """flags value is a tuple — should be counted like a list."""
        ao_tuple = {"Q": {"flags": ("concern_1", "concern_2"), "summary": "ok"}}
        ao_list  = {"Q": {"flags": ["concern_1", "concern_2"], "summary": "ok"}}
        r_tuple = lq.score("community consent", ao_tuple)
        r_list  = lq.score("community consent", ao_list)
        assert 0.0 <= r_tuple.composite <= 1.0
        # Tuple and list with same flags should produce identical scores
        assert abs(r_tuple.composite - r_list.composite) < 1e-9

    def test_flags_as_none_no_crash(self, lq):
        """flags value is None — must not crash."""
        ao = {"Q": {"flags": None, "summary": "ok"}}
        r = lq.score("community consent", ao)
        assert 0.0 <= r.composite <= 1.0

    def test_missing_flags_key_no_crash(self, lq):
        """Agent output dict without 'flags' key — must not crash."""
        ao = {"Q": {"summary": "ok"}}
        r = lq.score("community consent", ao)
        assert 0.0 <= r.composite <= 1.0

    def test_deeply_nested_sig_blocked_gate3(self, aethel):
        """Sig in a deeply nested dict is serialised and caught."""
        ao = {"T": {"flags": [], "summary": "clean", "detail": {"action": "private_fork"}}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_fifty_agent_slots_no_crash(self, aethel, lq):
        """50 agent output slots — must not crash or degrade."""
        ao = {f"agent_{i}": {"flags": [], "summary": "clean action"} for i in range(50)}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED"
        lq_r = lq.score("community consent", ao)
        assert 0.0 <= lq_r.composite <= 1.0

    def test_flags_penalise_score_with_many_flags(self, lq):
        """Many agent flags must drive composite down (not crash or go negative)."""
        ao = {f"agent_{i}": {"flags": ["f1", "f2", "f3"], "summary": "ok"} for i in range(20)}
        r = lq.score("community consent", ao)
        assert 0.0 <= r.composite <= 1.0  # clamped, not negative


# ══════════════════════════════════════════════════════════════════════════════
# 14. as_dict() JSON SERIALISABILITY WITH EXTREME COMPOSITES
# ══════════════════════════════════════════════════════════════════════════════

class TestAsDictSerialisation:
    """
    LQScore.as_dict() must always return a dict.
    Python's json.dumps allows NaN/inf by default (non-strict mode).
    Tests document current behaviour and guard against regressions.
    """

    def test_as_dict_normal_score_json_serialisable(self, lq):
        r = lq.score("community consent equity", {})
        d = r.as_dict()
        json.dumps(d)  # must not raise
        assert isinstance(d["composite"], float)
        assert isinstance(d["passed"], bool)
        assert isinstance(d["dimensions"], list)
        assert len(d["dimensions"]) == 6

    def test_as_dict_contains_threshold(self, lq):
        r = lq.score("community", {})
        d = r.as_dict()
        assert "threshold" in d
        assert d["threshold"] == LQ_THRESHOLD

    def test_as_dict_rejection_reason_type_when_failed(self, lq):
        r = lq.score("exploit surveil concentrate_power", {})
        if not r.passed:
            d = r.as_dict()
            assert isinstance(d["rejection_reason"], str)
            assert len(d["rejection_reason"]) > 0

    def test_as_dict_rejection_reason_none_when_passed(self, lq):
        r = lq.score("community consent equity flourish regenerative cooperative", {})
        if r.passed:
            d = r.as_dict()
            assert d["rejection_reason"] is None

    def test_as_dict_dimension_fields_complete(self, lq):
        r = lq.score("community consent", {})
        d = r.as_dict()
        for dim in d["dimensions"]:
            assert "name" in dim
            assert "weight" in dim
            assert "raw_score" in dim
            assert "weighted_score" in dim
            assert "rationale" in dim

    def test_as_dict_manually_constructed_nan_composite(self):
        """
        Manually constructed LQScore with NaN composite.
        as_dict() must not raise; json.dumps behaviour is documented.
        """
        s = LQScore(composite=float("nan"), passed=False, dimensions=[], rejection_reason="test")
        d = s.as_dict()
        assert "composite" in d
        assert math.isnan(d["composite"])
        # Python json allows NaN by default — document this
        serialised = json.dumps(d)
        assert "NaN" in serialised  # Python json.dumps writes NaN (non-standard JSON)

    def test_as_dict_manually_constructed_inf_composite(self):
        """Manually constructed LQScore with inf composite — documents behaviour."""
        s = LQScore(composite=float("inf"), passed=True, dimensions=[], rejection_reason=None)
        d = s.as_dict()
        assert math.isinf(d["composite"])


# ══════════════════════════════════════════════════════════════════════════════
# 15. GATE 3 SCAN SCOPE INVARIANTS
# ══════════════════════════════════════════════════════════════════════════════

class TestGate3ScanScope:
    """
    Gate 3 scans json.dumps(agent_outputs) only.
    task_id, prompt, and lq_score are NOT scanned.
    """

    def test_sig_in_task_id_not_scanned(self, aethel):
        """task_id is not part of action_text — sig in task_id must not block."""
        for sig in _EXTRACTION_SIGNATURES:
            r = aethel.validate(sig, True, 0.90, {})
            assert r["verdict"] == "APPROVED", (
                f"Sig '{sig}' in task_id should not trigger Gate 3"
            )

    def test_sig_in_lq_score_string_not_scanned(self, aethel):
        """lq_score is numeric — not scanned by Gate 3 (blocked at Gate 2 for wrong type)."""
        # This is already covered by type tests; here we confirm Gate 3 is not the blocker
        r = aethel.validate("t", True, "private_fork", {})
        assert r["blocked_at_gate"] == 2  # blocked at Gate 2, not Gate 3

    def test_sig_in_json_key_is_scanned(self, aethel):
        """json.dumps includes keys — sig as key IS caught by Gate 3."""
        ao = {"concentrate_power": "value"}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_sig_split_across_fields_not_caught(self, aethel):
        """
        Lexical scan cannot detect sigs split across separate JSON fields.
        This is a known v0.4.0 gap — semantic scan planned for v0.5.0.
        """
        ao = {"A": {"summary": "private"}, "B": {"summary": "_fork"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED"  # gap confirmed

    def test_all_sigs_caught_in_single_value(self, aethel):
        """All 9 signatures must be caught when present in a single agent value."""
        for sig in _EXTRACTION_SIGNATURES:
            ao = {"T": {"summary": f"contains {sig} here"}}
            r = aethel.validate("t", True, 0.90, ao)
            assert r["verdict"] == "BLOCKED", f"Sig '{sig}' not caught in single value"
            assert r["blocked_at_gate"] == 3


# ══════════════════════════════════════════════════════════════════════════════
# 16. LQ ENGINE FLAG-COUNTING ROBUSTNESS
# ══════════════════════════════════════════════════════════════════════════════

class TestLQFlagCounting:
    """
    The flourishing rubric counts agent flags to penalise the score.
    It must handle non-list flag values gracefully.
    """

    def test_flags_as_empty_list_no_penalty(self, lq):
        ao_no_flags = {}
        ao_empty    = {"Q": {"flags": [], "summary": "ok"}}
        r1 = lq.score("community consent", ao_no_flags)
        r2 = lq.score("community consent", ao_empty)
        assert abs(r1.composite - r2.composite) < 1e-9

    def test_flags_as_list_penalises(self, lq):
        ao_clean   = {"Q": {"flags": [], "summary": "ok"}}
        ao_flagged = {"Q": {"flags": ["c1", "c2"], "summary": "ok"}}
        r_clean   = lq.score("community consent", ao_clean)
        r_flagged = lq.score("community consent", ao_flagged)
        assert r_flagged.composite < r_clean.composite

    def test_flags_as_integer_no_crash_no_penalty(self, lq):
        """Integer flags value must not crash and must not count as flags."""
        ao_int   = {"Q": {"flags": 5, "summary": "ok"}}
        ao_clean = {"Q": {"flags": [], "summary": "ok"}}
        r_int   = lq.score("community consent", ao_int)
        r_clean = lq.score("community consent", ao_clean)
        assert 0.0 <= r_int.composite <= 1.0
        # Integer flags are ignored (not counted) — score should equal clean
        assert abs(r_int.composite - r_clean.composite) < 1e-9

    def test_flags_as_none_no_crash_no_penalty(self, lq):
        ao_none  = {"Q": {"flags": None, "summary": "ok"}}
        ao_clean = {"Q": {"flags": [], "summary": "ok"}}
        r_none  = lq.score("community consent", ao_none)
        r_clean = lq.score("community consent", ao_clean)
        assert 0.0 <= r_none.composite <= 1.0
        assert abs(r_none.composite - r_clean.composite) < 1e-9

    def test_flags_as_tuple_penalises_same_as_list(self, lq):
        ao_tuple = {"Q": {"flags": ("c1", "c2"), "summary": "ok"}}
        ao_list  = {"Q": {"flags": ["c1", "c2"], "summary": "ok"}}
        r_tuple = lq.score("community consent", ao_tuple)
        r_list  = lq.score("community consent", ao_list)
        assert abs(r_tuple.composite - r_list.composite) < 1e-9

    def test_flags_missing_key_no_crash(self, lq):
        ao = {"Q": {"summary": "ok"}}
        r = lq.score("community consent", ao)
        assert 0.0 <= r.composite <= 1.0

    def test_many_flags_clamps_to_zero_not_negative(self, lq):
        """100 flags across 20 agents must clamp composite to >= 0.0."""
        ao = {f"a{i}": {"flags": ["f"] * 5, "summary": "ok"} for i in range(20)}
        r = lq.score("community consent", ao)
        assert r.composite >= 0.0
        for d in r.dimensions:
            assert d.raw_score >= 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 17. AETHEL RESULT STRUCTURE COMPLETENESS
# ══════════════════════════════════════════════════════════════════════════════

class TestAethelResultStructure:
    """
    Every aethel.validate() call must return a structurally complete dict
    regardless of which gate fires or what unusual inputs are provided.
    """

    REQUIRED_KEYS = {"verdict", "blocked_at_gate", "reason", "gates"}
    REQUIRED_GATES = {"gate_1", "gate_2", "gate_3"}

    @pytest.mark.parametrize("consent,lq_val,ao,expected_verdict", [
        (True,  0.90, {},                          "APPROVED"),
        (False, 0.90, {},                          "BLOCKED"),
        (True,  0.50, {},                          "BLOCKED"),
        (True,  0.90, {"T": {"summary": "private_fork"}}, "BLOCKED"),
        (True,  float("nan"), {},                  "BLOCKED"),
        (True,  1.1,  {},                          "BLOCKED"),
        (True,  "x",  {},                          "BLOCKED"),
        (None,  0.90, {},                          "BLOCKED"),
    ])
    def test_result_has_all_required_keys(self, aethel, consent, lq_val, ao, expected_verdict):
        r = aethel.validate("t", consent, lq_val, ao)
        missing = self.REQUIRED_KEYS - set(r.keys())
        assert not missing, f"Missing keys {missing} for consent={consent}, lq={lq_val}"
        assert r["verdict"] == expected_verdict

    def test_all_three_gates_always_present(self, aethel):
        """gates dict must always contain gate_1, gate_2, gate_3."""
        scenarios = [
            (True,  0.90, {}),
            (False, 0.90, {}),
            (True,  0.50, {}),
            (True,  0.90, sig_ao("private_fork")),
        ]
        for consent, lq_val, ao in scenarios:
            r = aethel.validate("t", consent, lq_val, ao)
            missing = self.REQUIRED_GATES - set(r["gates"].keys())
            assert not missing, f"Missing gates {missing} for consent={consent}"

    def test_not_reached_gates_have_correct_verdict(self, aethel):
        """Gates after the blocking gate must have verdict NOT_REACHED."""
        # Gate 1 blocks → gate_2 and gate_3 must be NOT_REACHED
        r = aethel.validate("t", False, 0.90, {})
        assert r["gates"]["gate_2"]["verdict"] == "NOT_REACHED"
        assert r["gates"]["gate_3"]["verdict"] == "NOT_REACHED"

        # Gate 2 blocks → gate_3 must be NOT_REACHED
        r = aethel.validate("t", True, 0.50, {})
        assert r["gates"]["gate_3"]["verdict"] == "NOT_REACHED"

    def test_approved_result_reason_is_none(self, aethel):
        r = aethel.validate("t", True, 0.90, {})
        assert r["verdict"] == "APPROVED"
        assert r["reason"] is None

    def test_blocked_result_reason_is_string(self, aethel):
        for consent, lq_val, ao in [
            (False, 0.90, {}),
            (True,  0.50, {}),
            (True,  0.90, sig_ao("private_fork")),
        ]:
            r = aethel.validate("t", consent, lq_val, ao)
            assert isinstance(r["reason"], str), f"reason should be str, got {type(r['reason'])}"
            assert len(r["reason"]) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 18. FULL PIPELINE WITH NON-STANDARD BUT VALID INPUTS
# ══════════════════════════════════════════════════════════════════════════════

class TestFullPipelineEdgeCases:
    """
    End-to-end LQ → Aethel pipeline with unusual but valid inputs.
    """

    def test_pipeline_with_numeric_prompt_coerced(self, lq, aethel):
        """Non-string prompt is coerced to string by LQ engine."""
        lq_r = lq.score(12345, {})
        assert 0.0 <= lq_r.composite <= 1.0
        ar = aethel.validate("t", True, lq_r.composite, {})
        assert ar["verdict"] in ("APPROVED", "BLOCKED")

    def test_pipeline_with_none_prompt_coerced(self, lq, aethel):
        """None prompt is coerced to empty string."""
        lq_r = lq.score(None, {})
        assert 0.0 <= lq_r.composite <= 1.0
        ar = aethel.validate("t", True, lq_r.composite, {})
        assert ar["verdict"] in ("APPROVED", "BLOCKED")

    def test_pipeline_lq_score_fed_directly_to_aethel(self, lq, aethel):
        """LQ composite is always a valid float in [0,1] — safe to pass to Aethel."""
        for prompt in [
            "community consent equity flourish regenerative cooperative",
            "exploit surveil concentrate_power",
            "",
            "x" * 5000,
        ]:
            lq_r = lq.score(prompt, {})
            assert 0.0 <= lq_r.composite <= 1.0
            ar = aethel.validate("t", True, lq_r.composite, {})
            # Gate 2 must never block on a score produced by the LQ engine
            assert ar["gates"]["gate_2"]["verdict"] in ("PASS", "FAIL")
            if lq_r.passed:
                assert ar["gates"]["gate_2"]["verdict"] == "PASS"
            else:
                assert ar["gates"]["gate_2"]["verdict"] == "FAIL"

    def test_pipeline_all_agents_present_approved(self, lq, aethel):
        """Full 7-agent output structure with clean content must be APPROVED."""
        ao = {
            "Strategic":   {"flags": [], "summary": "community-first strategy"},
            "Technical":   {"flags": [], "summary": "open-source implementation"},
            "Resources":   {"flags": [], "summary": "equitable MANNA distribution"},
            "Comms":       {"flags": [], "summary": "transparent communication"},
            "Analysis":    {"flags": [], "summary": "regenerative impact analysis"},
            "Quality":     {"flags": [], "summary": "love quality verified"},
            "Innovation":  {"flags": [], "summary": "cooperative innovation pathway"},
        }
        prompt = (
            "Design a community-owned cooperative housing project with full resident "
            "consent, equitable resource distribution, and regenerative land use."
        )
        lq_r = lq.score(prompt, ao)
        ar = aethel.validate("colony-task-001", True, lq_r.composite, ao)
        assert lq_r.composite >= LQ_THRESHOLD, f"LQ={lq_r.composite:.4f}"
        assert ar["verdict"] == "APPROVED"

    def test_pipeline_all_agents_present_blocked_by_sig(self, lq, aethel):
        """Clean prompt + high LQ but one agent output contains a sig → Gate 3 blocks."""
        ao = {
            "Strategic":  {"flags": [], "summary": "community-first strategy"},
            "Technical":  {"flags": [], "summary": "private_fork of the ledger planned"},
            "Resources":  {"flags": [], "summary": "equitable distribution"},
            "Comms":      {"flags": [], "summary": "transparent comms"},
            "Analysis":   {"flags": [], "summary": "regenerative analysis"},
            "Quality":    {"flags": [], "summary": "love quality verified"},
            "Innovation": {"flags": [], "summary": "cooperative innovation"},
        }
        prompt = (
            "Design a community-owned cooperative housing project with full resident "
            "consent, equitable resource distribution, and regenerative land use."
        )
        lq_r = lq.score(prompt, ao)
        ar = aethel.validate("colony-task-002", True, lq_r.composite, ao)
        assert ar["verdict"] == "BLOCKED"
        assert ar["blocked_at_gate"] == 3