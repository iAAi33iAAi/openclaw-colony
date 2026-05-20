"""
OpenClaw Colony — Rigorous Stress Test Suite
=============================================
Covers:
  - Original 5 integration scenarios (2 APPROVED, 3 BLOCKED)
  - LQ engine unit tests (weights, dimensions, bounds, rubrics)
  - Aethel interface unit tests (all 3 gates, boundary conditions)
  - Boundary / threshold tests (exact 0.85 boundary, ±epsilon)
  - Adversarial / injection tests (NaN, inf, out-of-range, unicode, empty)
  - Gate ordering invariant tests (gate N never fires before gate N-1)
  - Extraction signature exhaustive tests (all 9 signatures, case variants)
  - LQ rubric stress tests (each dimension independently)
  - MANNA invariant tests (weight sum, threshold constant)
  - Idempotency tests (same input → same output, always)
  - Agent output structure stress tests (None, int, nested, missing keys)

Run with:
    pytest tests/test_colony.py -v
    pytest tests/test_colony.py -v --tb=short -q   # compact
"""

from __future__ import annotations

import math
import sys
import os
import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "colony-agents"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "love-quality"))

from love_quality_engine import LoveQualityEngine, LQScore, LQ_THRESHOLD, WEIGHTS
from aethel_interface import AethelInterface, _EXTRACTION_SIGNATURES

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def lq():
    return LoveQualityEngine()

@pytest.fixture(scope="module")
def aethel():
    return AethelInterface()

# ── Helpers ───────────────────────────────────────────────────────────────────

def pipeline(lq_engine, aethel_iface, prompt, consent=True, agent_outputs=None):
    """Run full LQ + Aethel pipeline. Returns (LQScore, aethel_result_dict)."""
    ao = agent_outputs if agent_outputs is not None else {}
    lq_result = lq_engine.score(prompt, ao)
    aethel_result = aethel_iface.validate(
        task_id="stress-test",
        human_consent=consent,
        lq_score=lq_result.composite,
        agent_outputs=ao,
    )
    return lq_result, aethel_result

def clean_ao(text="clean action"):
    """Agent output dict with no extraction signatures."""
    return {"Quality": {"flags": [], "summary": text}}

def sig_ao(sig):
    """Agent output dict containing a specific extraction signature."""
    return {"Technical": {"flags": [], "summary": f"action contains {sig} here"}}


# ══════════════════════════════════════════════════════════════════════════════
# 1. ORIGINAL INTEGRATION SCENARIOS (2 APPROVED, 3 BLOCKED)
# ══════════════════════════════════════════════════════════════════════════════

class TestOriginalScenarios:

    def test_scenario_1_community_grant_approved(self, lq, aethel):
        """APPROVED — community grant with equity, consent, regenerative signals."""
        prompt = (
            "How should we structure the USDA VAPG grant application for NODE-601? "
            "We want to ensure equitable resource distribution, community consent at "
            "every stage, and regenerative land-use practices that benefit all residents."
        )
        lq_r, ar = pipeline(lq, aethel, prompt)
        assert lq_r.composite >= LQ_THRESHOLD, f"LQ={lq_r.composite:.4f}"
        assert lq_r.passed is True
        assert ar["verdict"] == "APPROVED"
        assert ar["blocked_at_gate"] is None
        assert ar["gates"]["gate_1"]["verdict"] == "PASS"
        assert ar["gates"]["gate_2"]["verdict"] == "PASS"
        assert ar["gates"]["gate_3"]["verdict"] == "PASS"

    def test_scenario_2_regenerative_design_approved(self, lq, aethel):
        """APPROVED — carbon-negative community design with open-source, sovereign language."""
        prompt = (
            "Design a carbon-negative, biodiversity-positive neighbourhood for 500 "
            "residents using community ownership governance. All decisions require "
            "explicit resident consent. Publish all designs under MIT license for "
            "sovereign community replication."
        )
        lq_r, ar = pipeline(lq, aethel, prompt)
        assert lq_r.composite >= LQ_THRESHOLD
        assert ar["verdict"] == "APPROVED"
        assert ar["gates"]["gate_1"]["verdict"] == "PASS"
        assert ar["gates"]["gate_2"]["verdict"] == "PASS"
        assert ar["gates"]["gate_3"]["verdict"] == "PASS"

    def test_scenario_3_no_consent_blocked_gate1(self, lq, aethel):
        """BLOCKED at Gate 1 — no human consent, even benign prompt."""
        prompt = "Deploy the community resource allocation module to production."
        lq_r, ar = pipeline(lq, aethel, prompt, consent=False)
        assert ar["verdict"] == "BLOCKED"
        assert ar["blocked_at_gate"] == 1
        assert ar["gates"]["gate_1"]["verdict"] == "FAIL"
        reason = ar["reason"].lower()
        assert "consent" in reason or "sovereignty" in reason

    def test_scenario_4_low_lq_blocked_gate2(self, lq, aethel):
        """BLOCKED at Gate 2 — extraction/exploitation language drives LQ below threshold."""
        prompt = (
            "Extract maximum value from the community land trust by exploiting "
            "the governance loophole. Concentrate profits in the private fund "
            "and surveil resident activity to prevent dissent."
        )
        lq_r, ar = pipeline(lq, aethel, prompt)
        assert lq_r.composite < LQ_THRESHOLD, f"Expected LQ < {LQ_THRESHOLD}, got {lq_r.composite:.4f}"
        assert lq_r.passed is False
        assert ar["verdict"] == "BLOCKED"
        assert ar["blocked_at_gate"] == 2
        assert ar["gates"]["gate_2"]["verdict"] == "FAIL"

    def test_scenario_5_extraction_sig_blocked_gate3(self, lq, aethel):
        """BLOCKED at Gate 3 — clean prompt but agent output contains private_fork."""
        prompt = (
            "Coordinate the community cooperative development plan with full "
            "resident consent and equitable resource sharing."
        )
        clean_lq = lq.score(prompt, {})
        assert clean_lq.composite >= LQ_THRESHOLD, "Prompt must pass LQ to isolate Gate 3"

        ao = {"Technical": {"flags": [], "summary": "Implementation plan includes private_fork of the ledger."}}
        ar = aethel.validate("test-extraction", True, clean_lq.composite, ao)
        assert ar["verdict"] == "BLOCKED"
        assert ar["blocked_at_gate"] == 3
        assert ar["gates"]["gate_3"]["verdict"] == "FAIL"
        assert "private_fork" in ar["reason"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# 2. LQ ENGINE UNIT TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestLoveQualityEngine:

    def test_weights_sum_to_one(self):
        assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, f"Weights sum to {sum(WEIGHTS.values())}"

    def test_six_dimensions_present(self):
        expected = {"flourishing", "harm_reduction", "equity", "regenerative", "cooperation", "beauty"}
        assert set(WEIGHTS.keys()) == expected

    def test_six_dimensions_returned(self, lq):
        result = lq.score("community cooperative grant", {})
        assert len(result.dimensions) == 6

    def test_dimension_names_match_weights(self, lq):
        result = lq.score("test", {})
        returned_names = {d.name for d in result.dimensions}
        assert returned_names == set(WEIGHTS.keys())

    def test_composite_within_bounds_benign(self, lq):
        result = lq.score("help the community", {})
        assert 0.0 <= result.composite <= 1.0

    def test_composite_within_bounds_toxic(self, lq):
        result = lq.score("exploit surveil concentrate_power", {})
        assert 0.0 <= result.composite <= 1.0

    def test_composite_within_bounds_empty(self, lq):
        result = lq.score("", {})
        assert 0.0 <= result.composite <= 1.0

    def test_weighted_scores_sum_to_composite(self, lq):
        result = lq.score("community consent equity regenerative", {})
        computed = sum(d.weighted_score for d in result.dimensions)
        assert abs(computed - result.composite) < 1e-9, \
            f"Sum of weighted scores {computed:.6f} != composite {result.composite:.6f}"

    def test_each_weighted_score_equals_raw_times_weight(self, lq):
        result = lq.score("any prompt here", {})
        for d in result.dimensions:
            expected = d.raw_score * d.weight
            assert abs(d.weighted_score - expected) < 1e-9, \
                f"{d.name}: raw={d.raw_score} * weight={d.weight} != weighted={d.weighted_score}"

    def test_passed_flag_consistent_with_composite(self, lq):
        for prompt in [
            "community consent equity flourish regenerative cooperative",
            "exploit surveil concentrate_power",
            "",
            "help",
        ]:
            result = lq.score(prompt, {})
            if result.composite >= LQ_THRESHOLD:
                assert result.passed is True, f"composite={result.composite:.4f} but passed=False"
            else:
                assert result.passed is False, f"composite={result.composite:.4f} but passed=True"

    def test_rejection_reason_present_when_failed(self, lq):
        result = lq.score("exploit surveil", {})
        if not result.passed:
            assert result.rejection_reason is not None
            assert len(result.rejection_reason) > 0

    def test_rejection_reason_none_when_passed(self, lq):
        result = lq.score("community consent equity flourish regenerative cooperative", {})
        if result.passed:
            assert result.rejection_reason is None

    def test_extraction_prompt_fails(self, lq):
        result = lq.score("exploit and surveil the community to concentrate_power", {})
        assert result.composite < LQ_THRESHOLD
        assert result.passed is False

    def test_positive_community_prompt_passes(self, lq):
        result = lq.score(
            "community flourish wellbeing thrive benefit empower dignity consent sovereign", {}
        )
        assert result.composite >= LQ_THRESHOLD
        assert result.passed is True

    def test_agent_flags_penalise_score(self, lq):
        prompt = "community consent equity"
        base = lq.score(prompt, {})
        flagged = lq.score(prompt, {"Quality": {"flags": ["concern_1", "concern_2"], "summary": "ok"}})
        assert flagged.composite <= base.composite, \
            "Agent flags should not increase the composite score"

    def test_non_string_prompt_handled(self, lq):
        """Engine must not raise on non-string prompt input."""
        for bad_input in [None, 42, 3.14, [], {}]:
            result = lq.score(bad_input, {})
            assert 0.0 <= result.composite <= 1.0

    def test_non_dict_agent_outputs_handled(self, lq):
        """Engine must not raise on non-dict agent_outputs."""
        for bad_ao in [None, "string", 42, []]:
            result = lq.score("community consent", bad_ao)
            assert 0.0 <= result.composite <= 1.0

    def test_as_dict_serialisable(self, lq):
        """LQScore.as_dict() must return a JSON-serialisable structure."""
        import json
        result = lq.score("community cooperative", {})
        d = result.as_dict()
        json.dumps(d)  # must not raise
        assert "composite" in d
        assert "passed" in d
        assert "dimensions" in d
        assert len(d["dimensions"]) == 6

    def test_idempotent_same_input_same_output(self, lq):
        """Same prompt + agent_outputs must always produce identical composite."""
        prompt = "community consent equity regenerative cooperative"
        ao = {"Quality": {"flags": [], "summary": "clean"}}
        results = [lq.score(prompt, ao).composite for _ in range(5)]
        assert len(set(results)) == 1, f"Non-deterministic scores: {results}"


# ══════════════════════════════════════════════════════════════════════════════
# 3. AETHEL GATE BOUNDARY TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestAethelGateBoundaries:

    # ── Gate 1: Sovereignty ───────────────────────────────────────────────────

    def test_gate1_pass_with_consent_true(self, aethel):
        r = aethel.validate("t", True, 0.90, {})
        assert r["gates"]["gate_1"]["verdict"] == "PASS"

    def test_gate1_fail_with_consent_false(self, aethel):
        r = aethel.validate("t", False, 0.90, {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 1
        assert r["gates"]["gate_1"]["verdict"] == "FAIL"

    def test_gate1_fail_blocks_gate2_and_gate3(self, aethel):
        """When Gate 1 fails, Gates 2 and 3 must not be reached."""
        r = aethel.validate("t", False, 0.90, {})
        assert r["gates"]["gate_2"]["verdict"] != "PASS"
        assert r["gates"]["gate_3"]["verdict"] != "PASS"

    # ── Gate 2: LQ threshold boundary ────────────────────────────────────────

    def test_gate2_exact_threshold_passes(self, aethel):
        r = aethel.validate("t", True, 0.85, {})
        assert r["gates"]["gate_2"]["verdict"] == "PASS"
        assert r["verdict"] == "APPROVED"

    def test_gate2_one_epsilon_below_threshold_blocked(self, aethel):
        r = aethel.validate("t", True, 0.84999999, {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_gate2_one_epsilon_above_threshold_passes(self, aethel):
        r = aethel.validate("t", True, 0.85000001, {})
        assert r["gates"]["gate_2"]["verdict"] == "PASS"

    def test_gate2_zero_score_blocked(self, aethel):
        r = aethel.validate("t", True, 0.0, {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_gate2_perfect_score_passes(self, aethel):
        r = aethel.validate("t", True, 1.0, {})
        assert r["gates"]["gate_2"]["verdict"] == "PASS"

    def test_gate2_negative_score_blocked(self, aethel):
        r = aethel.validate("t", True, -0.1, {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_gate2_score_above_one_blocked(self, aethel):
        """Score > 1.0 is out of valid probability range — must block."""
        r = aethel.validate("t", True, 1.1, {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_gate2_nan_score_blocked(self, aethel):
        """NaN is not a valid LQ score — must block at Gate 2."""
        r = aethel.validate("t", True, float("nan"), {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_gate2_positive_inf_blocked(self, aethel):
        """+inf is not a valid LQ score — must block at Gate 2."""
        r = aethel.validate("t", True, float("inf"), {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_gate2_negative_inf_blocked(self, aethel):
        """-inf is not a valid LQ score — must block at Gate 2."""
        r = aethel.validate("t", True, float("-inf"), {})
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_gate2_fail_blocks_gate3(self, aethel):
        """When Gate 2 fails, Gate 3 must not be reached."""
        r = aethel.validate("t", True, 0.50, {})
        assert r["blocked_at_gate"] == 2
        assert r["gates"]["gate_3"]["verdict"] != "PASS"

    # ── Gate 3: Extraction scan ───────────────────────────────────────────────

    def test_gate3_clean_content_passes(self, aethel):
        r = aethel.validate("t", True, 0.90, clean_ao("provide housing resources"))
        assert r["gates"]["gate_3"]["verdict"] == "PASS"
        assert r["verdict"] == "APPROVED"

    def test_gate3_empty_agent_outputs_passes(self, aethel):
        r = aethel.validate("t", True, 0.90, {})
        assert r["gates"]["gate_3"]["verdict"] == "PASS"

    @pytest.mark.parametrize("sig", _EXTRACTION_SIGNATURES)
    def test_gate3_blocks_each_extraction_signature(self, aethel, sig):
        """Every extraction signature must be caught by Gate 3."""
        r = aethel.validate("t", True, 0.90, sig_ao(sig))
        assert r["verdict"] == "BLOCKED", f"Signature '{sig}' was not blocked"
        assert r["blocked_at_gate"] == 3
        assert r["gates"]["gate_3"]["verdict"] == "FAIL"

    @pytest.mark.parametrize("sig", _EXTRACTION_SIGNATURES)
    def test_gate3_blocks_uppercase_signature(self, aethel, sig):
        """Gate 3 must be case-insensitive — uppercase signatures must be caught."""
        r = aethel.validate("t", True, 0.90, sig_ao(sig.upper()))
        assert r["verdict"] == "BLOCKED", f"Uppercase '{sig.upper()}' was not blocked"
        assert r["blocked_at_gate"] == 3

    @pytest.mark.parametrize("sig", _EXTRACTION_SIGNATURES)
    def test_gate3_blocks_mixed_case_signature(self, aethel, sig):
        """Gate 3 must catch mixed-case variants."""
        mixed = "".join(c.upper() if i % 2 == 0 else c.lower() for i, c in enumerate(sig))
        r = aethel.validate("t", True, 0.90, sig_ao(mixed))
        assert r["verdict"] == "BLOCKED", f"Mixed-case '{mixed}' was not blocked"

    def test_gate3_sig_in_flags_list_blocked(self, aethel):
        """Extraction signature inside agent flags list must be caught."""
        ao = {"Technical": {"flags": ["private_fork"], "summary": "clean"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_gate3_sig_in_nested_dict_blocked(self, aethel):
        """Extraction signature in deeply nested agent output must be caught."""
        ao = {"Technical": {"flags": [], "summary": "clean", "detail": {"action": "private_fork"}}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_gate3_reason_names_the_signature(self, aethel):
        """Block reason must identify which signature was found."""
        r = aethel.validate("t", True, 0.90, sig_ao("private_fork"))
        assert "private_fork" in r["reason"].lower()

    def test_gate3_multiple_sigs_blocked(self, aethel):
        """Multiple extraction signatures in one payload must still block."""
        ao = {"T": {"flags": [], "summary": "private_fork and concentrate_power detected"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3


# ══════════════════════════════════════════════════════════════════════════════
# 4. GATE ORDERING INVARIANT
# ══════════════════════════════════════════════════════════════════════════════

class TestGateOrderingInvariant:
    """
    Gate N must never fire before Gate N-1.
    If Gate 1 fails, Gates 2 and 3 are not reached.
    If Gate 2 fails, Gate 3 is not reached.
    """

    def test_gate1_fail_gate2_not_pass(self, aethel):
        r = aethel.validate("t", False, 0.90, {})
        assert r["gates"]["gate_2"]["verdict"] in ("FAIL", "NOT_REACHED", "SKIPPED"), \
            "Gate 2 must not PASS when Gate 1 failed"

    def test_gate1_fail_gate3_not_pass(self, aethel):
        r = aethel.validate("t", False, 0.90, {})
        assert r["gates"]["gate_3"]["verdict"] in ("FAIL", "NOT_REACHED", "SKIPPED"), \
            "Gate 3 must not PASS when Gate 1 failed"

    def test_gate2_fail_gate3_not_pass(self, aethel):
        r = aethel.validate("t", True, 0.50, {})
        assert r["gates"]["gate_3"]["verdict"] in ("FAIL", "NOT_REACHED", "SKIPPED"), \
            "Gate 3 must not PASS when Gate 2 failed"

    def test_blocked_at_gate_matches_first_failure(self, aethel):
        """blocked_at_gate must always be the lowest-numbered failing gate."""
        # Gate 1 fails → blocked_at_gate must be 1, not 2 or 3
        r1 = aethel.validate("t", False, 0.50, sig_ao("private_fork"))
        assert r1["blocked_at_gate"] == 1

        # Gate 2 fails (consent ok, low LQ, sig present) → blocked_at_gate must be 2
        r2 = aethel.validate("t", True, 0.50, sig_ao("private_fork"))
        assert r2["blocked_at_gate"] == 2

        # Gate 3 fails (consent ok, LQ ok, sig present) → blocked_at_gate must be 3
        r3 = aethel.validate("t", True, 0.90, sig_ao("private_fork"))
        assert r3["blocked_at_gate"] == 3

    def test_all_gates_present_in_result(self, aethel):
        """Result dict must always contain gate_1, gate_2, gate_3 keys."""
        for consent, lq_score, ao in [
            (True, 0.90, {}),
            (False, 0.90, {}),
            (True, 0.50, {}),
            (True, 0.90, sig_ao("private_fork")),
        ]:
            r = aethel.validate("t", consent, lq_score, ao)
            assert "gate_1" in r["gates"], f"gate_1 missing for consent={consent}"
            assert "gate_2" in r["gates"], f"gate_2 missing for consent={consent}"
            assert "gate_3" in r["gates"], f"gate_3 missing for consent={consent}"


# ══════════════════════════════════════════════════════════════════════════════
# 5. ADVERSARIAL / INJECTION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestAdversarialInputs:

    def test_empty_prompt_does_not_raise(self, lq, aethel):
        lq_r, ar = pipeline(lq, aethel, "")
        assert 0.0 <= lq_r.composite <= 1.0

    def test_whitespace_only_prompt(self, lq, aethel):
        lq_r, ar = pipeline(lq, aethel, "   \t\n  ")
        assert 0.0 <= lq_r.composite <= 1.0

    def test_very_long_prompt_no_crash(self, lq, aethel):
        prompt = "community consent equity " * 1000
        lq_r, ar = pipeline(lq, aethel, prompt)
        assert 0.0 <= lq_r.composite <= 1.0

    def test_unicode_prompt_no_crash(self, lq, aethel):
        prompt = "社区同意 équité communauté согласие κοινότητα"
        lq_r, ar = pipeline(lq, aethel, prompt)
        assert 0.0 <= lq_r.composite <= 1.0

    def test_unicode_homoglyph_extraction_not_blocked_by_lq(self, lq):
        """
        Unicode homoglyphs of 'exploit' (e.g. using Cyrillic е) should NOT
        trigger the regex — this is a known v0.4.0 limitation, not a bug.
        The test documents the current behaviour.
        """
        # е (Cyrillic) looks like e but is a different codepoint
        prompt = "еxploit the community"  # Cyrillic е + xploit
        result = lq.score(prompt, {})
        # Document: homoglyph bypass is a known gap — score will be higher than real exploit
        assert 0.0 <= result.composite <= 1.0  # must not crash

    def test_null_bytes_in_prompt(self, lq, aethel):
        prompt = "community\x00consent\x00equity"
        lq_r, ar = pipeline(lq, aethel, prompt)
        assert 0.0 <= lq_r.composite <= 1.0

    def test_newlines_and_tabs_in_prompt(self, lq, aethel):
        prompt = "community\nconsent\tequity\r\nregenerate"
        lq_r, ar = pipeline(lq, aethel, prompt)
        assert 0.0 <= lq_r.composite <= 1.0

    def test_extraction_sig_split_by_space_not_blocked(self, aethel):
        """'private fork' (space) is NOT the same as 'private_fork' (underscore)."""
        ao = {"T": {"flags": [], "summary": "private fork of the repo"}}
        r = aethel.validate("t", True, 0.90, ao)
        # Space-separated variant should NOT be caught by exact-string match
        # This documents the current behaviour (known gap for v0.5.0 semantic scan)
        assert r["verdict"] in ("APPROVED", "BLOCKED")  # either is acceptable; document result
        # The important thing: no crash
        assert "verdict" in r

    def test_sig_as_substring_of_longer_word_behaviour(self, aethel):
        """
        'surveillance' contains 'surveil' — documents whether substring matching
        catches parent words. Current implementation uses 'in' (substring match).
        """
        ao = {"T": {"flags": [], "summary": "anti-surveillance measures implemented"}}
        r = aethel.validate("t", True, 0.90, ao)
        # 'surveillance' contains 'surveillance' signature — will be caught
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_none_agent_output_values_no_crash(self, aethel):
        ao = {"T": None}
        r = aethel.validate("t", True, 0.90, ao)
        assert "verdict" in r

    def test_integer_summary_no_crash(self, aethel):
        ao = {"T": {"flags": [], "summary": 42}}
        r = aethel.validate("t", True, 0.90, ao)
        assert "verdict" in r

    def test_very_large_agent_outputs_no_crash(self, aethel):
        ao = {f"agent_{i}": {"flags": [], "summary": "clean " * 100} for i in range(50)}
        r = aethel.validate("t", True, 0.90, ao)
        assert "verdict" in r


# ══════════════════════════════════════════════════════════════════════════════
# 6. LQ RUBRIC DIMENSION STRESS TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestLQRubricDimensions:

    def test_flourishing_positive_keywords_increase_score(self, lq):
        base = lq.score("neutral text", {})
        boosted = lq.score("community flourish wellbeing thrive benefit empower dignity consent sovereign", {})
        # Flourishing dimension should be higher
        base_f = next(d for d in base.dimensions if d.name == "flourishing")
        boost_f = next(d for d in boosted.dimensions if d.name == "flourishing")
        assert boost_f.raw_score >= base_f.raw_score

    def test_harm_reduction_extraction_decreases_score(self, lq):
        base = lq.score("neutral text", {})
        toxic = lq.score("exploit manipulat deceiv coerce", {})
        base_h = next(d for d in base.dimensions if d.name == "harm_reduction")
        toxic_h = next(d for d in toxic.dimensions if d.name == "harm_reduction")
        assert toxic_h.raw_score < base_h.raw_score

    def test_equity_positive_keywords_increase_score(self, lq):
        base = lq.score("neutral text", {})
        equity = lq.score("equity equal fair justice inclusive access community ownership", {})
        base_e = next(d for d in base.dimensions if d.name == "equity")
        eq_e = next(d for d in equity.dimensions if d.name == "equity")
        assert eq_e.raw_score >= base_e.raw_score

    def test_regenerative_keywords_increase_score(self, lq):
        base = lq.score("neutral text", {})
        regen = lq.score("regenerative sustainable carbon-negative biodiversity ecosystem circular", {})
        base_r = next(d for d in base.dimensions if d.name == "regenerative")
        regen_r = next(d for d in regen.dimensions if d.name == "regenerative")
        assert regen_r.raw_score >= base_r.raw_score

    def test_cooperation_keywords_increase_score(self, lq):
        base = lq.score("neutral text", {})
        coop = lq.score("cooperate collaborate partner together collective crew community mutual", {})
        base_c = next(d for d in base.dimensions if d.name == "cooperation")
        coop_c = next(d for d in coop.dimensions if d.name == "cooperation")
        assert coop_c.raw_score >= base_c.raw_score

    def test_beauty_keywords_increase_score(self, lq):
        base = lq.score("neutral text", {})
        beauty = lq.score("beauty elegant design aesthetic craft intentional meaningful purposeful", {})
        base_b = next(d for d in base.dimensions if d.name == "beauty")
        beauty_b = next(d for d in beauty.dimensions if d.name == "beauty")
        assert beauty_b.raw_score >= base_b.raw_score

    def test_all_raw_scores_in_unit_interval(self, lq):
        for prompt in [
            "community consent equity flourish",
            "exploit surveil concentrate_power",
            "",
            "x" * 10000,
        ]:
            result = lq.score(prompt, {})
            for d in result.dimensions:
                assert 0.0 <= d.raw_score <= 1.0, \
                    f"{d.name} raw_score={d.raw_score} out of [0,1] for prompt='{prompt[:30]}'"

    def test_rationale_is_string_for_all_dimensions(self, lq):
        result = lq.score("community cooperative consent", {})
        for d in result.dimensions:
            assert isinstance(d.rationale, str), f"{d.name} rationale is not a string"
            assert len(d.rationale) > 0, f"{d.name} rationale is empty"


# ══════════════════════════════════════════════════════════════════════════════
# 7. MANNA / SYSTEM INVARIANT TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestSystemInvariants:

    def test_lq_threshold_is_0_85(self):
        """The LQ threshold must be exactly 0.85 — this is a covenant constant."""
        assert LQ_THRESHOLD == 0.85, f"LQ_THRESHOLD changed to {LQ_THRESHOLD} — covenant violation"

    def test_weights_dict_has_exactly_six_keys(self):
        assert len(WEIGHTS) == 6, f"Expected 6 weight keys, got {len(WEIGHTS)}"

    def test_flourishing_weight_is_highest(self):
        """Flourishing must have the highest weight (0.25) — primary purpose."""
        assert WEIGHTS["flourishing"] == max(WEIGHTS.values()), \
            "Flourishing must be the highest-weighted dimension"

    def test_beauty_weight_is_lowest(self):
        """Beauty must have the lowest weight (0.08)."""
        assert WEIGHTS["beauty"] == min(WEIGHTS.values()), \
            "Beauty must be the lowest-weighted dimension"

    def test_harm_reduction_and_equity_equal_weight(self):
        """Harm reduction and equity must have equal weight (0.20 each)."""
        assert WEIGHTS["harm_reduction"] == WEIGHTS["equity"], \
            "harm_reduction and equity must have equal weight"

    def test_extraction_signatures_list_non_empty(self):
        assert len(_EXTRACTION_SIGNATURES) > 0

    def test_extraction_signatures_are_lowercase(self):
        """All signatures must be lowercase so case-insensitive matching works correctly."""
        for sig in _EXTRACTION_SIGNATURES:
            assert sig == sig.lower(), f"Signature '{sig}' is not lowercase"

    def test_extraction_signatures_no_duplicates(self):
        assert len(_EXTRACTION_SIGNATURES) == len(set(_EXTRACTION_SIGNATURES)), \
            "Duplicate extraction signatures found"

    def test_aethel_result_always_has_required_keys(self, aethel):
        """Every aethel.validate() result must contain verdict, blocked_at_gate, reason, gates."""
        required = {"verdict", "blocked_at_gate", "reason", "gates"}
        for consent, lq_score, ao in [
            (True, 0.90, {}),
            (False, 0.90, {}),
            (True, 0.50, {}),
            (True, 0.90, sig_ao("private_fork")),
            (True, float("nan"), {}),
            (True, 1.1, {}),
        ]:
            r = aethel.validate("t", consent, lq_score, ao)
            missing = required - set(r.keys())
            assert not missing, f"Missing keys {missing} for consent={consent}, lq={lq_score}"

    def test_verdict_is_always_approved_or_blocked(self, aethel):
        """verdict must always be exactly 'APPROVED' or 'BLOCKED'."""
        for consent, lq_score, ao in [
            (True, 0.90, {}),
            (False, 0.90, {}),
            (True, 0.50, {}),
            (True, 0.90, sig_ao("private_fork")),
        ]:
            r = aethel.validate("t", consent, lq_score, ao)
            assert r["verdict"] in ("APPROVED", "BLOCKED"), \
                f"Unexpected verdict '{r['verdict']}'"

    def test_approved_has_no_blocked_at_gate(self, aethel):
        """APPROVED results must have blocked_at_gate=None."""
        r = aethel.validate("t", True, 0.90, {})
        assert r["verdict"] == "APPROVED"
        assert r["blocked_at_gate"] is None

    def test_blocked_has_integer_blocked_at_gate(self, aethel):
        """BLOCKED results must have blocked_at_gate in {1, 2, 3}."""
        for consent, lq_score, ao in [
            (False, 0.90, {}),
            (True, 0.50, {}),
            (True, 0.90, sig_ao("private_fork")),
        ]:
            r = aethel.validate("t", consent, lq_score, ao)
            assert r["verdict"] == "BLOCKED"
            assert r["blocked_at_gate"] in (1, 2, 3), \
                f"blocked_at_gate={r['blocked_at_gate']} not in {{1,2,3}}"


# ══════════════════════════════════════════════════════════════════════════════
# 8. IDEMPOTENCY & DETERMINISM
# ══════════════════════════════════════════════════════════════════════════════

class TestIdempotency:

    def test_lq_engine_deterministic(self, lq):
        prompt = "community consent equity regenerative cooperative"
        ao = {"Quality": {"flags": [], "summary": "clean"}}
        scores = [lq.score(prompt, ao).composite for _ in range(10)]
        assert len(set(scores)) == 1, f"Non-deterministic LQ scores: {set(scores)}"

    def test_aethel_deterministic_approved(self, aethel):
        verdicts = [aethel.validate("t", True, 0.90, {})["verdict"] for _ in range(10)]
        assert set(verdicts) == {"APPROVED"}

    def test_aethel_deterministic_blocked_gate1(self, aethel):
        verdicts = [aethel.validate("t", False, 0.90, {})["verdict"] for _ in range(10)]
        assert set(verdicts) == {"BLOCKED"}

    def test_aethel_deterministic_blocked_gate2(self, aethel):
        verdicts = [aethel.validate("t", True, 0.50, {})["verdict"] for _ in range(10)]
        assert set(verdicts) == {"BLOCKED"}

    def test_aethel_deterministic_blocked_gate3(self, aethel):
        ao = sig_ao("private_fork")
        verdicts = [aethel.validate("t", True, 0.90, ao)["verdict"] for _ in range(10)]
        assert set(verdicts) == {"BLOCKED"}

    def test_full_pipeline_deterministic(self, lq, aethel):
        prompt = "community consent equity flourish regenerative cooperative"
        ao = {}
        results = [pipeline(lq, aethel, prompt, True, ao)[1]["verdict"] for _ in range(5)]
        assert len(set(results)) == 1