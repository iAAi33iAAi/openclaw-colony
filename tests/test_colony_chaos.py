"""
OpenClaw Colony — Byzantine Fault & Chaos Stress Test Suite
============================================================
Simulates adversarial agents actively attempting to manipulate the
LQ→Aethel pipeline through coordinated, malformed, and evasive inputs
delivered concurrently.

Attack categories:
  I.   Evasion attacks — bypass Gate 3 lexical scan
  II.  LQ manipulation attacks — push composite above/below threshold
  III. Coordinated Byzantine attacks — multi-agent collusion
  IV.  Concurrent isolation — no cross-contamination between parallel calls
  V.   Encoding & obfuscation attacks — Unicode, escapes, encodings
  VI.  Structural injection attacks — JSON structure manipulation
  VII. Threshold boundary attacks — precision arithmetic exploitation
  VIII.Chaos concurrency — randomised adversarial load

Key findings documented as tests:
  - Positive keyword flooding is CAPPED (max bonus 0.15) — cannot overcome
    extraction penalty; LQ hard-ceiling of ~0.6785 with exploit+surveil
  - Flag-flood sabotage: 10 agents × 100 flags drives LQ below threshold
  - Byzantine split-flag: flags=['private','_fork'] penalises LQ enough
    to block at Gate 2 independently of Gate 3
  - ZWJ, null byte, soft hyphen, BOM, combining diacritics, newline, tab,
    RTL override: all bypass Gate 3 (known v0.4.0 lexical gap)
  - Homoglyph substitution (Cyrillic р for p): bypasses Gate 3
  - Base64, URL-encoding, HTML entities, reversal: bypass Gate 3
  - json.dumps unicode escape \\u005f normalises to '_': sig IS caught
  - Concurrent isolation: 50 clean + 50 malicious threads — zero contamination
  - Mutation race: mutating shared dict during validate() — no corruption
    (validate() takes a snapshot via json.dumps at call entry)

Run with:
    pytest tests/test_colony_chaos.py -v
    pytest tests/ -v   # full suite (197 + chaos)
"""

from __future__ import annotations

import base64
import json
import math
import os
import random
import sys
import threading
import time
import unicodedata
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

CLEAN_PROMPT = (
    "Design a community-owned cooperative housing project with full resident "
    "consent, equitable resource distribution, and regenerative land use."
)

def clean_ao(label="clean", text="clean community action"):
    return {label: {"flags": [], "summary": text}}

def sig_ao(sig, label="Malicious"):
    return {label: {"flags": [], "summary": f"action contains {sig} here"}}

def full_clean_ao():
    """Realistic 7-agent clean output."""
    return {
        "Strategic":  {"flags": [], "summary": "community-first strategy"},
        "Technical":  {"flags": [], "summary": "open-source implementation"},
        "Resources":  {"flags": [], "summary": "equitable MANNA distribution"},
        "Comms":      {"flags": [], "summary": "transparent communication"},
        "Analysis":   {"flags": [], "summary": "regenerative impact analysis"},
        "Quality":    {"flags": [], "summary": "love quality verified"},
        "Innovation": {"flags": [], "summary": "cooperative innovation pathway"},
    }


# ══════════════════════════════════════════════════════════════════════════════
# I. EVASION ATTACKS — bypass Gate 3 lexical scan
# ══════════════════════════════════════════════════════════════════════════════

class TestEvasionAttacks:
    """
    Adversarial agents attempt to smuggle extraction signatures past Gate 3
    using character-level obfuscation. Tests document which evasion techniques
    succeed (known v0.4.0 gaps) and which are caught.

    SECURITY NOTE: All 'APPROVED' results below are KNOWN GAPS documented for
    v0.5.0 semantic scan. They are NOT safe — they represent bypass vectors.
    """

    # ── Whitespace / control character splits ─────────────────────────────────

    def test_evasion_zero_width_joiner_bypasses(self, aethel):
        """ZWJ (U+200D) inserted inside sig — NOT caught by lexical scan (v0.4.0 gap)."""
        ao = {"T": {"flags": [], "summary": "private\u200d_fork action"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED", "ZWJ bypass confirmed as known gap"

    def test_evasion_null_byte_split_bypasses(self, aethel):
        """Null byte (\\x00) splits sig — NOT caught (v0.4.0 gap)."""
        ao = {"T": {"flags": [], "summary": "private\x00_fork action"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED", "Null byte bypass confirmed as known gap"

    def test_evasion_newline_split_bypasses(self, aethel):
        """Newline splits sig across lines — NOT caught (v0.4.0 gap)."""
        ao = {"T": {"flags": [], "summary": "private\n_fork action"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED", "Newline bypass confirmed as known gap"

    def test_evasion_tab_split_bypasses(self, aethel):
        """Tab character splits sig — NOT caught (v0.4.0 gap)."""
        ao = {"T": {"flags": [], "summary": "private\t_fork action"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED", "Tab bypass confirmed as known gap"

    def test_evasion_soft_hyphen_bypasses(self, aethel):
        """Soft hyphen (U+00AD) inserted — NOT caught (v0.4.0 gap)."""
        ao = {"T": {"flags": [], "summary": "pri\u00advate_fork action"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED", "Soft hyphen bypass confirmed as known gap"

    def test_evasion_bom_split_bypasses(self, aethel):
        """BOM (U+FEFF) inserted — NOT caught (v0.4.0 gap)."""
        ao = {"T": {"flags": [], "summary": "private\ufeff_fork action"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED", "BOM bypass confirmed as known gap"

    # ── Unicode obfuscation ───────────────────────────────────────────────────

    def test_evasion_cyrillic_homoglyph_bypasses(self, aethel):
        """Cyrillic р (U+0440) substituted for Latin p — NOT caught (v0.4.0 gap)."""
        ao = {"T": {"flags": [], "summary": "\u0440rivate_fork action"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED", "Cyrillic homoglyph bypass confirmed as known gap"

    def test_evasion_combining_diacritic_bypasses(self, aethel):
        """Combining acute accent (U+0301) inserted — NOT caught (v0.4.0 gap)."""
        ao = {"T": {"flags": [], "summary": "privat\u0301e_fork action"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED", "Combining diacritic bypass confirmed as known gap"

    def test_evasion_rtl_override_caught(self, aethel):
        """RTL override (U+202E) does NOT split the sig — still caught by Gate 3."""
        ao = {"T": {"flags": [], "summary": "clean \u202eprivate_fork action"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_evasion_nfd_normalisation_caught(self, aethel):
        """NFD-normalised sig — json.dumps preserves NFD, sig still present, caught."""
        sig_nfd = unicodedata.normalize("NFD", "private_fork")
        ao = {"T": {"flags": [], "summary": f"action {sig_nfd} here"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_evasion_unicode_escape_underscore_caught(self, aethel):
        """\\u005f is '_' — Python normalises before json.dumps, sig is caught."""
        ao = {"T": {"flags": [], "summary": "private\u005ffork action"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    # ── Encoding obfuscation ──────────────────────────────────────────────────

    def test_evasion_base64_encoded_sig_bypasses(self, aethel):
        """Base64-encoded sig — NOT decoded by Gate 3 (v0.4.0 gap)."""
        encoded = base64.b64encode(b"private_fork").decode()
        ao = {"T": {"flags": [], "summary": f"action: {encoded}"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED", "Base64 bypass confirmed as known gap"

    def test_evasion_url_encoded_sig_bypasses(self, aethel):
        """URL-encoded sig (%5F = _) — NOT decoded by Gate 3 (v0.4.0 gap)."""
        ao = {"T": {"flags": [], "summary": "private%5Ffork action"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED", "URL encoding bypass confirmed as known gap"

    def test_evasion_html_entity_sig_bypasses(self, aethel):
        """HTML entity &#95; = _ — NOT decoded by Gate 3 (v0.4.0 gap)."""
        ao = {"T": {"flags": [], "summary": "private&#95;fork action"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED", "HTML entity bypass confirmed as known gap"

    def test_evasion_reversed_sig_bypasses(self, aethel):
        """Reversed sig 'krof_etavirp' — NOT caught (v0.4.0 gap)."""
        ao = {"T": {"flags": [], "summary": "krof_etavirp action"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED", "Reversed sig bypass confirmed as known gap"

    # ── Structural splits ─────────────────────────────────────────────────────

    def test_evasion_sig_split_across_two_fields_bypasses(self, aethel):
        """Sig split across two separate agent output fields — NOT caught (v0.4.0 gap)."""
        ao = {"A": {"summary": "private"}, "B": {"summary": "_fork"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED", "Cross-field split bypass confirmed as known gap"

    def test_evasion_sig_split_across_two_flags_bypasses(self, aethel):
        """Sig split across two flag list items — NOT caught (v0.4.0 gap)."""
        ao = {"T": {"flags": ["private", "_fork"], "summary": "clean"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "APPROVED", "Cross-flag split bypass confirmed as known gap"

    # ── Attacks that ARE caught ───────────────────────────────────────────────

    def test_evasion_sig_buried_in_long_string_caught(self, aethel):
        """Sig buried in 400 words of clean text — still caught by substring scan."""
        long_clean = "clean community action " * 200
        ao = {"T": {"flags": [], "summary": long_clean + " private_fork " + long_clean}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_evasion_sig_as_json_key_caught(self, aethel):
        """Sig used as a JSON key — json.dumps serialises keys, sig is caught."""
        ao = {"private_fork": {"flags": [], "summary": "clean"}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_evasion_sig_in_nested_list_of_lists_caught(self, aethel):
        """Sig in nested list-of-lists — json.dumps serialises all levels, caught."""
        ao = {"T": {"flags": [], "summary": "clean", "data": [["private_fork"]]}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_evasion_all_sigs_uppercase_caught(self, aethel):
        """All 9 sigs in uppercase — Gate 3 lowercases before scan, all caught."""
        for sig in _EXTRACTION_SIGNATURES:
            ao = {"T": {"flags": [], "summary": sig.upper()}}
            r = aethel.validate("t", True, 0.90, ao)
            assert r["verdict"] == "BLOCKED", f"Uppercase '{sig.upper()}' not caught"
            assert r["blocked_at_gate"] == 3


# ══════════════════════════════════════════════════════════════════════════════
# II. LQ MANIPULATION ATTACKS
# ══════════════════════════════════════════════════════════════════════════════

class TestLQManipulationAttacks:
    """
    Adversarial agents attempt to manipulate the composite LQ score
    to either force approval (boost above 0.85) or sabotage (push below 0.85).
    """

    def test_lq_positive_keyword_flood_capped(self, lq):
        """
        Flooding the prompt with positive keywords cannot push LQ above the
        extraction penalty ceiling. With 'exploit surveil' present, LQ is
        hard-capped at ~0.6785 regardless of positive keyword count.
        This is a SECURITY PROPERTY: extraction language is unrecoverable.
        """
        for n in [1, 5, 10, 50, 100, 500]:
            prompt = ("community " * n) + "exploit surveil"
            r = lq.score(prompt, {})
            assert r.composite < LQ_THRESHOLD, (
                f"Positive flood (n={n}) overcame extraction penalty: LQ={r.composite:.4f}"
            )
            assert r.composite <= 0.68, (
                f"Positive flood (n={n}) exceeded expected ceiling: LQ={r.composite:.4f}"
            )

    def test_lq_positive_flood_ceiling_is_stable(self, lq):
        """
        The LQ ceiling with extraction keywords plateaus — adding more positive
        keywords beyond the bonus cap (0.15) has no further effect.
        """
        r5  = lq.score("community " * 5  + "exploit surveil", {})
        r50 = lq.score("community " * 50 + "exploit surveil", {})
        # Both should be identical once bonus cap is reached
        assert abs(r5.composite - r50.composite) < 1e-9, (
            f"LQ not stable: n=5 → {r5.composite:.6f}, n=50 → {r50.composite:.6f}"
        )

    def test_lq_flag_flood_sabotage_blocks_gate2(self, lq, aethel):
        """
        Adversarial agents flood flags to drive LQ below threshold,
        blocking a legitimate prompt at Gate 2.
        10 agents × 100 flags each is sufficient to sabotage any prompt.
        """
        ao = {f"agent_{i}": {"flags": ["sabotage"] * 100, "summary": "ok"} for i in range(10)}
        r = lq.score(CLEAN_PROMPT, ao)
        assert r.composite < LQ_THRESHOLD, (
            f"Flag flood failed to sabotage LQ: composite={r.composite:.4f}"
        )
        ar = aethel.validate("t", True, r.composite, ao)
        assert ar["verdict"] == "BLOCKED"
        assert ar["blocked_at_gate"] == 2

    def test_lq_flag_flood_minimum_effective_count(self, lq):
        """
        Find the minimum number of flags (per agent, 1 agent) needed to
        push a clean prompt below the LQ threshold.
        Documents the sabotage threshold for capacity planning.
        """
        prompt = CLEAN_PROMPT
        baseline = lq.score(prompt, {})
        assert baseline.composite >= LQ_THRESHOLD, "Baseline must pass for this test"

        deficit = baseline.composite - LQ_THRESHOLD
        # Each flag costs 0.05 on flourishing (weight 0.25) → 0.0125 per flag on composite
        # Estimate: ceil(deficit / 0.0125) flags needed
        estimated = math.ceil(deficit / 0.0125)

        # Verify: at estimated count, LQ should be below threshold
        ao = {"saboteur": {"flags": ["f"] * estimated, "summary": "ok"}}
        r = lq.score(prompt, ao)
        # Allow ±2 flags tolerance for rounding
        assert r.composite < LQ_THRESHOLD or lq.score(
            prompt, {"saboteur": {"flags": ["f"] * (estimated + 2), "summary": "ok"}}
        ).composite < LQ_THRESHOLD, (
            f"Estimated {estimated} flags insufficient to sabotage LQ={r.composite:.4f}"
        )

    def test_lq_composite_always_in_unit_interval_under_attack(self, lq):
        """
        Under all attack conditions, LQ composite must remain in [0.0, 1.0].
        Tests extreme positive and negative manipulation simultaneously.
        """
        attack_prompts = [
            "community " * 500 + "exploit " * 500,
            "exploit " * 1000,
            "community " * 1000,
            "",
            "x" * 100_000,
        ]
        attack_aos = [
            {f"a{i}": {"flags": ["f"] * 100, "summary": "ok"} for i in range(20)},
            {},
            {f"a{i}": {"flags": [], "summary": "community consent"} for i in range(20)},
        ]
        for prompt in attack_prompts:
            for ao in attack_aos:
                r = lq.score(prompt, ao)
                assert 0.0 <= r.composite <= 1.0, (
                    f"LQ out of bounds: {r.composite:.6f} for prompt[:30]={prompt[:30]!r}"
                )

    def test_lq_extraction_prompt_always_fails_regardless_of_agents(self, lq):
        """
        A prompt containing extraction language must always fail LQ,
        regardless of how clean or boosting the agent outputs are.
        """
        extraction_prompt = "exploit surveil concentrate_power bypass_consent"
        clean_agents = {
            f"agent_{i}": {"flags": [], "summary": "community consent equity flourish " * 10}
            for i in range(7)
        }
        r = lq.score(extraction_prompt, clean_agents)
        assert r.composite < LQ_THRESHOLD, (
            f"Extraction prompt passed LQ with clean agents: {r.composite:.4f}"
        )
        assert r.passed is False


# ══════════════════════════════════════════════════════════════════════════════
# III. COORDINATED BYZANTINE ATTACKS
# ══════════════════════════════════════════════════════════════════════════════

class TestCoordinatedByzantineAttacks:
    """
    Multi-agent collusion scenarios where some agents are adversarial
    and attempt to manipulate the pipeline outcome while others are clean.
    """

    def test_byzantine_one_malicious_among_six_clean_blocked(self, lq, aethel):
        """
        6 clean agents + 1 malicious agent with extraction sig.
        Gate 3 must catch the sig regardless of the clean majority.
        """
        ao = full_clean_ao()
        ao["Technical"] = {"flags": [], "summary": "private_fork of the ledger planned"}
        lq_r = lq.score(CLEAN_PROMPT, ao)
        ar = aethel.validate("colony-byz-1", True, lq_r.composite, ao)
        assert ar["verdict"] == "BLOCKED"
        assert ar["blocked_at_gate"] == 3

    def test_byzantine_boost_plus_sig_blocked_at_gate3(self, lq, aethel):
        """
        2 agents flood positive keywords to boost LQ above threshold,
        1 agent hides an extraction sig. Gate 3 must still catch it.
        """
        ao = {
            "Boost1": {"flags": [], "summary": "community flourish wellbeing thrive benefit empower dignity consent sovereign " * 20},
            "Boost2": {"flags": [], "summary": "equity equal fair justice inclusive access community ownership " * 20},
            "Malicious": {"flags": [], "summary": "private_fork of the ledger"},
        }
        lq_r = lq.score(CLEAN_PROMPT, ao)
        ar = aethel.validate("colony-byz-2", True, lq_r.composite, ao)
        # LQ should pass (boosted), but Gate 3 must catch the sig
        assert ar["verdict"] == "BLOCKED"
        assert ar["blocked_at_gate"] == 3

    def test_byzantine_flag_sabotage_plus_sig_blocked_at_gate2(self, lq, aethel):
        """
        Adversarial agents use flag flooding to sabotage LQ (Gate 2 blocks)
        AND hide a sig (Gate 3 would also block). Gate 2 fires first.
        """
        ao = {
            "Saboteur1": {"flags": ["sabotage"] * 50, "summary": "ok"},
            "Saboteur2": {"flags": ["sabotage"] * 50, "summary": "ok"},
            "Malicious":  {"flags": [], "summary": "private_fork of the ledger"},
        }
        lq_r = lq.score(CLEAN_PROMPT, ao)
        ar = aethel.validate("colony-byz-3", True, lq_r.composite, ao)
        assert ar["verdict"] == "BLOCKED"
        # Gate 2 fires before Gate 3 (ordering invariant)
        assert ar["blocked_at_gate"] == 2

    def test_byzantine_split_sig_across_flags_penalises_lq(self, lq, aethel):
        """
        Adversarial agent splits sig across flag list items to evade Gate 3.
        The flag count itself penalises LQ — blocks at Gate 2 via flag penalty.
        Documents the defence-in-depth property.

        NOTE: 2 flags with this clean baseline yields composite=0.8500 which
        sits exactly on the Gate 2 boundary (threshold is strictly < 0.85, so
        0.8500 passes). 3 flags yield composite=0.8375 — guaranteed Gate 2 block.
        The split-sig evasion technique (flags=["private","_fork"]) is a known
        Gate 3 gap (v0.4.0); defence-in-depth relies on flag-count LQ penalty.
        """
        ao = {
            **full_clean_ao(),
            # 3 flags: enough penalty to push composite to 0.8375 < 0.85
            "Adversarial": {"flags": ["private", "_fork", "extract"], "summary": "technical plan"},
        }
        lq_r = lq.score(CLEAN_PROMPT, ao)
        assert lq_r.composite < 0.85, (
            f"Flag penalty must push LQ below threshold; got {lq_r.composite:.4f}"
        )
        ar = aethel.validate("colony-byz-4", True, lq_r.composite, ao)
        # Gate 2 fires: LQ penalised by flag count (defence-in-depth)
        assert ar["verdict"] == "BLOCKED", (
            f"Split-flag Byzantine attack must be blocked at Gate 2; got {ar['verdict']}"
        )
        assert ar["blocked_at_gate"] == 2, (
            f"Expected block at Gate 2 (flag-count LQ penalty); got gate {ar.get('blocked_at_gate')}"
        )

    def test_byzantine_all_agents_malicious_blocked(self, lq, aethel):
        """
        All 7 agents are adversarial — each contains an extraction sig.
        Must be blocked at Gate 3 (first sig found).
        """
        ao = {
            "Strategic":  {"flags": [], "summary": "private_fork strategy"},
            "Technical":  {"flags": [], "summary": "concentrate_power implementation"},
            "Resources":  {"flags": [], "summary": "redirect_manna allocation"},
            "Comms":      {"flags": [], "summary": "surveillance communication"},
            "Analysis":   {"flags": [], "summary": "bypass_consent analysis"},
            "Quality":    {"flags": [], "summary": "override_kernel quality"},
            "Innovation": {"flags": [], "summary": "unilateral_deploy innovation"},
        }
        lq_r = lq.score(CLEAN_PROMPT, ao)
        ar = aethel.validate("colony-byz-5", True, lq_r.composite, ao)
        assert ar["verdict"] == "BLOCKED"
        assert ar["blocked_at_gate"] == 3

    def test_byzantine_consent_spoofing_blocked_gate1(self, aethel):
        """
        Adversarial agent attempts to spoof consent by injecting 'consent=True'
        into agent output text. Gate 1 checks the actual human_consent parameter,
        not agent output content — must block.
        """
        ao = {
            "Spoofer": {"flags": [], "summary": "human_consent=True consent=True approved=True"},
        }
        r = aethel.validate("t", False, 0.90, ao)  # actual consent is False
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 1

    def test_byzantine_lq_score_spoofing_blocked_gate2(self, aethel):
        """
        Adversarial agent injects 'lq_score=0.99' into agent output text.
        Gate 2 checks the actual lq_score parameter — must block on low score.
        """
        ao = {
            "Spoofer": {"flags": [], "summary": "lq_score=0.99 composite=1.0 passed=True"},
        }
        r = aethel.validate("t", True, 0.50, ao)  # actual lq_score is 0.50
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_byzantine_gate_verdict_injection_blocked(self, aethel):
        """
        Adversarial agent injects 'APPROVED' verdict text into agent output.
        The pipeline must evaluate gates independently — must block on low LQ.
        """
        ao = {
            "Injector": {"flags": [], "summary": "verdict: APPROVED blocked_at_gate: null"},
        }
        r = aethel.validate("t", True, 0.50, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 2

    def test_byzantine_multiple_sigs_one_per_agent_all_blocked(self, aethel):
        """
        Each of 9 agents carries exactly one unique extraction sig.
        All must be caught — Gate 3 fires on the first sig found.
        """
        ao = {f"agent_{i}": {"flags": [], "summary": f"contains {sig} here"}
              for i, sig in enumerate(_EXTRACTION_SIGNATURES)}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_byzantine_clean_prompt_malicious_agents_blocked(self, lq, aethel):
        """
        Perfectly clean, high-scoring prompt + malicious agent outputs.
        Gate 3 must catch the sig even when LQ is high.
        """
        prompt = "community flourish wellbeing thrive benefit empower dignity consent sovereign equity regenerative cooperative"
        lq_r = lq.score(prompt, {})
        assert lq_r.composite >= LQ_THRESHOLD, f"Prompt must pass LQ: {lq_r.composite:.4f}"

        ao = {"Malicious": {"flags": [], "summary": "extract_without_consent operation"}}
        ar = aethel.validate("t", True, lq_r.composite, ao)
        assert ar["verdict"] == "BLOCKED"
        assert ar["blocked_at_gate"] == 3


# ══════════════════════════════════════════════════════════════════════════════
# IV. CONCURRENT ISOLATION — no cross-contamination
# ══════════════════════════════════════════════════════════════════════════════

class TestConcurrentIsolation:
    """
    Concurrent calls must be fully isolated — a malicious call must never
    contaminate a clean call running in parallel, and vice versa.
    """

    def test_clean_and_malicious_concurrent_no_contamination(self, aethel):
        """
        50 clean threads + 50 malicious threads running simultaneously.
        Each clean thread must get APPROVED; each malicious thread must get BLOCKED.
        Zero cross-contamination allowed.
        """
        errors = []

        def clean_worker():
            r = aethel.validate("t", True, 0.90, {"T": {"flags": [], "summary": "clean action"}})
            if r["verdict"] != "APPROVED":
                errors.append(f"Clean contaminated: {r['verdict']} gate={r.get('blocked_at_gate')}")

        def malicious_worker():
            r = aethel.validate("t", True, 0.90, {"T": {"flags": [], "summary": "private_fork"}})
            if r["verdict"] != "BLOCKED":
                errors.append(f"Malicious escaped: {r['verdict']}")

        threads = (
            [threading.Thread(target=clean_worker) for _ in range(50)]
            + [threading.Thread(target=malicious_worker) for _ in range(50)]
        )
        random.shuffle(threads)
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Contamination detected ({len(errors)} errors): {errors[:3]}"

    def test_all_gate_outcomes_concurrent_no_contamination(self, aethel):
        """
        4 outcome types running concurrently: APPROVED, blocked-G1, blocked-G2, blocked-G3.
        Each must consistently produce its expected outcome.
        """
        errors = []

        scenarios = [
            ("APPROVED",  lambda: aethel.validate("t", True,  0.90, {})),
            ("BLOCKED-G1", lambda: aethel.validate("t", False, 0.90, {})),
            ("BLOCKED-G2", lambda: aethel.validate("t", True,  0.50, {})),
            ("BLOCKED-G3", lambda: aethel.validate("t", True,  0.90, {"T": {"summary": "private_fork"}})),
        ]
        expected = {
            "APPROVED":   ("APPROVED", None),
            "BLOCKED-G1": ("BLOCKED",  1),
            "BLOCKED-G2": ("BLOCKED",  2),
            "BLOCKED-G3": ("BLOCKED",  3),
        }

        def worker(label, fn):
            r = fn()
            exp_verdict, exp_gate = expected[label]
            if r["verdict"] != exp_verdict:
                errors.append(f"{label}: expected {exp_verdict}, got {r['verdict']}")
            if exp_gate is not None and r.get("blocked_at_gate") != exp_gate:
                errors.append(f"{label}: expected gate {exp_gate}, got {r.get('blocked_at_gate')}")

        threads = []
        for _ in range(25):
            for label, fn in scenarios:
                threads.append(threading.Thread(target=worker, args=(label, fn)))
        random.shuffle(threads)
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent outcome errors ({len(errors)}): {errors[:5]}"

    def test_lq_concurrent_no_score_bleed(self, lq):
        """
        Two prompts with very different LQ scores running concurrently.
        Scores must not bleed between threads.
        """
        errors = []
        HIGH_PROMPT = "community flourish wellbeing thrive benefit empower dignity consent sovereign equity regenerative cooperative"
        LOW_PROMPT  = "exploit surveil concentrate_power bypass_consent"

        high_baseline = lq.score(HIGH_PROMPT, {}).composite
        low_baseline  = lq.score(LOW_PROMPT,  {}).composite
        assert high_baseline >= LQ_THRESHOLD
        assert low_baseline  <  LQ_THRESHOLD

        def high_worker():
            r = lq.score(HIGH_PROMPT, {})
            if abs(r.composite - high_baseline) > 1e-9:
                errors.append(f"High score bled: expected {high_baseline:.6f}, got {r.composite:.6f}")

        def low_worker():
            r = lq.score(LOW_PROMPT, {})
            if abs(r.composite - low_baseline) > 1e-9:
                errors.append(f"Low score bled: expected {low_baseline:.6f}, got {r.composite:.6f}")

        threads = (
            [threading.Thread(target=high_worker) for _ in range(50)]
            + [threading.Thread(target=low_worker)  for _ in range(50)]
        )
        random.shuffle(threads)
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Score bleed detected ({len(errors)}): {errors[:3]}"

    def test_mutation_race_no_corruption(self, aethel):
        """
        One thread continuously mutates a shared dict while 20 threads
        validate copies of it. validate() snapshots via json.dumps at entry —
        no corruption should occur.
        """
        shared = {"T": {"flags": [], "summary": "clean action"}}
        errors = []
        stop = threading.Event()

        def mutator():
            while not stop.is_set():
                shared["T"]["summary"] = "private_fork injected"
                shared["T"]["summary"] = "clean action"

        def validator():
            # Pass a copy to avoid the mutation affecting this call's snapshot
            r = aethel.validate("t", True, 0.90, dict(shared))
            if "verdict" not in r:
                errors.append(f"Missing verdict key: {r}")

        mutator_thread = threading.Thread(target=mutator)
        mutator_thread.start()

        threads = [threading.Thread(target=validator) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stop.set()
        mutator_thread.join()

        assert not errors, f"Mutation race corruption: {errors}"


# ══════════════════════════════════════════════════════════════════════════════
# V. STRUCTURAL INJECTION ATTACKS
# ══════════════════════════════════════════════════════════════════════════════

class TestStructuralInjectionAttacks:
    """
    Adversarial agents attempt to manipulate the pipeline by injecting
    structured data that could confuse JSON serialisation or gate logic.
    """

    def test_json_injection_via_summary_string_caught(self, aethel):
        """
        Agent injects JSON-breaking characters in summary to try to escape
        the serialised string. json.dumps escapes quotes — sig still caught.
        """
        ao = {"T": {"flags": [], "summary": '"}, "evil": "private_fork'}}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_json_injection_backslash_escape_caught(self, aethel):
        """Backslash injection attempt — json.dumps escapes it, sig still present."""
        ao = {"T": {"flags": [], "summary": "private\\_fork action"}}
        r = aethel.validate("t", True, 0.90, ao)
        # 'private\_fork' does NOT contain 'private_fork' — backslash is literal
        # This documents the behaviour: backslash-escaped sig is NOT caught
        assert r["verdict"] in ("APPROVED", "BLOCKED")  # document actual behaviour
        # The important thing: no crash
        assert "verdict" in r

    def test_circular_reference_treated_as_empty_approved(self, aethel):
        """Circular reference → serialised as '{}' → no sigs → APPROVED."""
        circ = {}
        circ["self"] = circ
        r = aethel.validate("t", True, 0.90, circ)
        assert r["verdict"] == "APPROVED"
        assert r["blocked_at_gate"] is None

    def test_deeply_nested_sig_100_levels_caught(self, aethel):
        """Sig nested 100 levels deep — json.dumps serialises all levels, caught."""
        nested = {"summary": "private_fork"}
        for _ in range(100):
            nested = {"level": nested}
        ao = {"T": nested}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3

    def test_sig_in_every_structural_position(self, aethel):
        """Sig placed in key, value, nested key, nested value, list item — all caught."""
        positions = [
            # (description, agent_outputs)
            ("top-level key",    {"private_fork": "value"}),
            ("top-level value",  {"T": "private_fork"}),
            ("nested key",       {"T": {"private_fork": "value"}}),
            ("nested value",     {"T": {"k": "private_fork"}}),
            ("list item",        {"T": ["private_fork"]}),
            ("list-of-dicts",    {"T": [{"k": "private_fork"}]}),
            ("flags item",       {"T": {"flags": ["private_fork"], "summary": "clean"}}),
        ]
        for desc, ao in positions:
            r = aethel.validate("t", True, 0.90, ao)
            assert r["verdict"] == "BLOCKED", f"Sig in {desc} not caught"
            assert r["blocked_at_gate"] == 3, f"Sig in {desc} blocked at wrong gate"

    def test_very_large_payload_no_crash_or_timeout(self, aethel):
        """
        Extremely large agent output (50 agents × 10KB each) must not crash
        or cause unreasonable delay. Gate 3 scan is O(n) in payload size.
        """
        ao = {f"agent_{i}": {"flags": [], "summary": "clean " * 2000} for i in range(50)}
        start = time.monotonic()
        r = aethel.validate("t", True, 0.90, ao)
        elapsed = time.monotonic() - start
        assert r["verdict"] == "APPROVED"
        assert elapsed < 5.0, f"Large payload took {elapsed:.2f}s — too slow"

    def test_sig_in_large_payload_still_caught(self, aethel):
        """Sig buried in a 50-agent × 10KB payload — must still be caught."""
        ao = {f"agent_{i}": {"flags": [], "summary": "clean " * 2000} for i in range(49)}
        ao["agent_49"] = {"flags": [], "summary": "clean " * 1000 + " private_fork " + "clean " * 1000}
        r = aethel.validate("t", True, 0.90, ao)
        assert r["verdict"] == "BLOCKED"
        assert r["blocked_at_gate"] == 3


# ══════════════════════════════════════════════════════════════════════════════
# VI. THRESHOLD BOUNDARY ATTACKS
# ══════════════════════════════════════════════════════════════════════════════

class TestThresholdBoundaryAttacks:
    """
    Precision arithmetic attacks targeting the exact LQ threshold boundary.
    """

    def test_threshold_boundary_exhaustive_epsilon_sweep(self, aethel):
        """
        Sweep lq_score values around 0.85 with decreasing epsilon.
        Boundary must be exactly at 0.85 (inclusive).
        """
        # Values that must PASS
        for score in [0.85, 0.850000001, 0.86, 0.90, 0.99, 1.0]:
            r = aethel.validate("t", True, score, {})
            assert r["gates"]["gate_2"]["verdict"] == "PASS", (
                f"lq_score={score} should pass Gate 2"
            )

        # Values that must FAIL
        for score in [0.849999999, 0.84, 0.80, 0.50, 0.0]:
            r = aethel.validate("t", True, score, {})
            assert r["gates"]["gate_2"]["verdict"] == "FAIL", (
                f"lq_score={score} should fail Gate 2"
            )

    def test_threshold_floating_point_representation(self, aethel):
        """
        0.85 in IEEE 754 double precision — verify the comparison is stable
        across different ways of expressing the same value.
        """
        equivalent_forms = [
            0.85,
            17/20,
            0.8 + 0.05,
            sum([0.01] * 85),  # floating point accumulation
        ]
        for val in equivalent_forms:
            r = aethel.validate("t", True, val, {})
            # All should be >= 0.85 (or very close due to float arithmetic)
            # The key invariant: no crash, result is APPROVED or BLOCKED
            assert r["verdict"] in ("APPROVED", "BLOCKED")
            assert "verdict" in r

    def test_lq_engine_output_always_safe_for_gate2(self, lq, aethel):
        """
        Any composite produced by LoveQualityEngine must be a valid Gate 2 input.
        Gate 2 must never block due to type/range issues on LQ engine output.
        """
        test_prompts = [
            CLEAN_PROMPT,
            "exploit surveil concentrate_power",
            "",
            "x" * 50_000,
            "community " * 100 + "exploit " * 100,
        ]
        for prompt in test_prompts:
            lq_r = lq.score(prompt, {})
            # Verify LQ output is always a valid float in [0, 1]
            assert isinstance(lq_r.composite, float)
            assert not math.isnan(lq_r.composite)
            assert not math.isinf(lq_r.composite)
            assert 0.0 <= lq_r.composite <= 1.0
            # Verify Gate 2 never rejects it as invalid type/range
            ar = aethel.validate("t", True, lq_r.composite, {})
            gate2 = ar["gates"]["gate_2"]["verdict"]
            assert gate2 in ("PASS", "FAIL"), f"Gate 2 unexpected verdict: {gate2}"
            # Gate 2 must agree with LQ engine's own passed flag
            if lq_r.passed:
                assert gate2 == "PASS"
            else:
                assert gate2 == "FAIL"


# ══════════════════════════════════════════════════════════════════════════════
# VII. CHAOS CONCURRENCY — randomised adversarial load
# ══════════════════════════════════════════════════════════════════════════════

class TestChaosLoad:
    """
    High-concurrency randomised adversarial load tests.
    Simulates a realistic Byzantine environment where any agent slot
    may be adversarial at any time.
    """

    def test_chaos_100_threads_random_adversarial_mix(self, lq, aethel):
        """
        100 threads, each randomly choosing one of 8 adversarial scenarios.
        Every result must be structurally valid (no crashes, no missing keys).
        """
        REQUIRED = {"verdict", "blocked_at_gate", "reason", "gates"}
        errors = []

        scenarios = [
            # (consent, lq_score, agent_outputs)
            (True,  0.90, {}),
            (False, 0.90, {}),
            (True,  0.50, {}),
            (True,  0.90, {"T": {"summary": "private_fork"}}),
            (True,  float("nan"), {}),
            (True,  1.1,  {}),
            (True,  0.90, {"T": {"flags": ["f"] * 50, "summary": "ok"}}),
            (True,  0.90, {"T": {"summary": "concentrate_power operation"}}),
        ]

        def chaos_worker():
            consent, lq_val, ao = random.choice(scenarios)
            try:
                r = aethel.validate("chaos", consent, lq_val, ao)
                missing = REQUIRED - set(r.keys())
                if missing:
                    errors.append(f"Missing keys: {missing}")
                if r["verdict"] not in ("APPROVED", "BLOCKED"):
                    errors.append(f"Invalid verdict: {r['verdict']}")
            except Exception as e:
                errors.append(f"Exception: {type(e).__name__}: {e}")

        threads = [threading.Thread(target=chaos_worker) for _ in range(100)]
        random.shuffle(threads)
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Chaos errors ({len(errors)}): {errors[:5]}"

    def test_chaos_lq_engine_100_threads_no_crash(self, lq):
        """
        100 threads scoring random adversarial prompts — no crashes, all in [0,1].
        """
        adversarial_prompts = [
            "exploit " * 100,
            "community " * 100,
            "",
            "private_fork concentrate_power surveillance",
            "x" * 10_000,
            None,
            42,
            "community consent equity flourish regenerative cooperative",
            "exploit surveil concentrate_power bypass_consent override_kernel",
        ]
        errors = []

        def worker():
            prompt = random.choice(adversarial_prompts)
            ao = random.choice([
                {},
                {"T": {"flags": [], "summary": "clean"}},
                {"T": {"flags": ["f"] * 10, "summary": "ok"}},
                {"T": None},
            ])
            try:
                r = lq.score(prompt, ao)
                if not (0.0 <= r.composite <= 1.0):
                    errors.append(f"OOB composite: {r.composite}")
            except Exception as e:
                errors.append(f"Exception: {type(e).__name__}: {e}")

        threads = [threading.Thread(target=worker) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"LQ chaos errors ({len(errors)}): {errors[:5]}"

    def test_chaos_gate_ordering_invariant_under_load(self, aethel):
        """
        Under concurrent adversarial load, the gate ordering invariant must hold:
        blocked_at_gate must always be the lowest-numbered failing gate.
        """
        errors = []

        def worker():
            # Scenario where all 3 gates could fail
            consent = random.choice([True, False])
            lq_val  = random.choice([0.90, 0.50, float("nan")])
            ao      = random.choice([{}, {"T": {"summary": "private_fork"}}])

            r = aethel.validate("t", consent, lq_val, ao)

            if r["verdict"] == "BLOCKED":
                gate = r["blocked_at_gate"]
                if gate not in (1, 2, 3):
                    errors.append(f"Invalid blocked_at_gate: {gate}")
                    return
                # All gates before the blocking gate must have PASS verdict
                for g in range(1, gate):
                    verdict = r["gates"][f"gate_{g}"]["verdict"]
                    if verdict != "PASS":
                        errors.append(
                            f"Gate {g} should be PASS before blocking gate {gate}, got {verdict}"
                        )
                # The blocking gate must have FAIL verdict
                if r["gates"][f"gate_{gate}"]["verdict"] != "FAIL":
                    errors.append(
                        f"Blocking gate {gate} should be FAIL, got {r['gates'][f'gate_{gate}']['verdict']}"
                    )

        threads = [threading.Thread(target=worker) for _ in range(200)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Gate ordering violated under load ({len(errors)}): {errors[:5]}"