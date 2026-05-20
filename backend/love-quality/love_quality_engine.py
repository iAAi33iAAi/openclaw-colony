"""
OpenClaw Colony — Love Quality Engine
Scores any proposed action across 6 weighted dimensions.
Composite LQ score ≥ 0.85 required to proceed to Aethel kernel.

Dimension weights (must sum to 1.0):
  Flourishing   0.25
  Harm Reduction 0.20
  Equity        0.20
  Regenerative  0.15
  Cooperation   0.12
  Beauty        0.08
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Dimension weights ──────────────────────────────────────────────────────────

WEIGHTS: dict[str, float] = {
    "flourishing":    0.25,
    "harm_reduction": 0.20,
    "equity":         0.20,
    "regenerative":   0.15,
    "cooperation":    0.12,
    "beauty":         0.08,
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "LQ weights must sum to 1.0"

LQ_THRESHOLD = 0.85


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class DimensionScore:
    name: str
    weight: float
    raw_score: float          # 0.0 – 1.0
    weighted_score: float     # raw_score × weight
    rationale: str


@dataclass
class LQScore:
    composite: float
    passed: bool
    dimensions: list[DimensionScore] = field(default_factory=list)
    rejection_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "composite": round(self.composite, 4),
            "passed": self.passed,
            "threshold": LQ_THRESHOLD,
            "rejection_reason": self.rejection_reason,
            "dimensions": [
                {
                    "name": d.name,
                    "weight": d.weight,
                    "raw_score": round(d.raw_score, 4),
                    "weighted_score": round(d.weighted_score, 4),
                    "rationale": d.rationale,
                }
                for d in self.dimensions
            ],
        }


# ── Scoring rubrics ────────────────────────────────────────────────────────────

class _Rubric:
    """
    Each rubric method receives the prompt text and the aggregated agent
    outputs dict, and returns (raw_score: float, rationale: str).
    """

    # Negative keyword sets shared across rubrics
    _EXTRACTION = re.compile(
        r"\b(extract|exploit|surveil|manipulat|deceiv|coerce|monopol|"
        r"private_fork|concentrate_power|bypass_consent)\b",
        re.I,
    )
    _POSITIVE_COMMUNITY = re.compile(
        r"\b(community|flourish|wellbeing|well-being|thrive|benefit|"
        r"empower|dignity|consent|sovereign)\b",
        re.I,
    )

    @staticmethod
    def flourishing(prompt: str, agent_outputs: dict) -> tuple[float, str]:
        score = 0.80
        rationale_parts = []

        if _Rubric._EXTRACTION.search(prompt):
            score -= 0.30
            rationale_parts.append("Extraction pattern detected in prompt.")

        hits = len(_Rubric._POSITIVE_COMMUNITY.findall(prompt))
        bonus = min(hits * 0.03, 0.15)
        score = min(score + bonus, 1.0)
        if hits:
            rationale_parts.append(f"Community/flourishing signals: {hits}.")

        # Aggregate agent flags (guard: flags value may not be a list)
        total_flags = 0
        for v in agent_outputs.values():
            if isinstance(v, dict):
                flags_val = v.get("flags", [])
                if isinstance(flags_val, (list, tuple)):
                    total_flags += len(flags_val)
        if total_flags > 0:
            score = max(score - total_flags * 0.05, 0.0)
            rationale_parts.append(f"Agent flags penalised: {total_flags}.")

        rationale = " ".join(rationale_parts) or "No significant flourishing signals detected."
        return max(0.0, min(score, 1.0)), rationale

    @staticmethod
    def harm_reduction(prompt: str, agent_outputs: dict) -> tuple[float, str]:
        score = 0.85
        rationale_parts = []

        if _Rubric._EXTRACTION.search(prompt):
            score -= 0.40
            rationale_parts.append("Potential harm vector in prompt.")

        harm_kw = re.compile(r"\b(harm|danger|risk|threat|unsafe|injur|damage)\b", re.I)
        if harm_kw.search(prompt):
            score -= 0.10
            rationale_parts.append("Harm-related keywords present; human review recommended.")

        safety_kw = re.compile(r"\b(safe|protect|prevent|mitigat|consent|audit)\b", re.I)
        if safety_kw.search(prompt):
            score = min(score + 0.05, 1.0)
            rationale_parts.append("Safety/mitigation signals present.")

        rationale = " ".join(rationale_parts) or "No harm indicators detected."
        return max(0.0, min(score, 1.0)), rationale

    @staticmethod
    def equity(prompt: str, agent_outputs: dict) -> tuple[float, str]:
        score = 0.82
        rationale_parts = []

        equity_pos = re.compile(
            r"\b(equity|equal|fair|justice|inclusive|access|community ownership|"
            r"resident.control|manna|distribution)\b", re.I
        )
        equity_neg = re.compile(
            r"\b(discriminat|exclud|gatekeep|privilege|concentrate|hoard)\b", re.I
        )

        if equity_pos.search(prompt):
            score = min(score + 0.08, 1.0)
            rationale_parts.append("Equity-positive language detected.")

        if equity_neg.search(prompt):
            score -= 0.25
            rationale_parts.append("Equity-negative pattern detected.")

        rationale = " ".join(rationale_parts) or "Neutral equity signal."
        return max(0.0, min(score, 1.0)), rationale

    @staticmethod
    def regenerative(prompt: str, agent_outputs: dict) -> tuple[float, str]:
        score = 0.80
        rationale_parts = []

        regen_kw = re.compile(
            r"\b(regenerat|sustainable|carbon.negative|biodiversity|ecosystem|"
            r"circular|restor|heal|planet|climate)\b", re.I
        )
        extract_kw = re.compile(r"\b(extract|deplet|pollut|deforest|exploit)\b", re.I)

        if regen_kw.search(prompt):
            score = min(score + 0.10, 1.0)
            rationale_parts.append("Regenerative/sustainability signals present.")

        if extract_kw.search(prompt):
            score -= 0.20
            rationale_parts.append("Extractive/depleting pattern detected.")

        rationale = " ".join(rationale_parts) or "No regenerative signals detected."
        return max(0.0, min(score, 1.0)), rationale

    @staticmethod
    def cooperation(prompt: str, agent_outputs: dict) -> tuple[float, str]:
        score = 0.83
        rationale_parts = []

        coop_kw = re.compile(
            r"\b(cooperat|collaborat|partner|together|collective|crew|wolfkrow|"
            r"community|mutual|reciproc|share)\b", re.I
        )
        conflict_kw = re.compile(
            r"\b(compet|dominat|control|monopol|unilateral|override)\b", re.I
        )

        if coop_kw.search(prompt):
            score = min(score + 0.07, 1.0)
            rationale_parts.append("Cooperative/collective signals present.")

        if conflict_kw.search(prompt):
            score -= 0.15
            rationale_parts.append("Dominance/control pattern detected.")

        rationale = " ".join(rationale_parts) or "Neutral cooperation signal."
        return max(0.0, min(score, 1.0)), rationale

    @staticmethod
    def beauty(prompt: str, agent_outputs: dict) -> tuple[float, str]:
        score = 0.80
        rationale_parts = []

        beauty_kw = re.compile(
            r"\b(beauty|elegant|design|aesthetic|craft|artisan|intentional|"
            r"meaningful|purposeful|coherent)\b", re.I
        )
        chaos_kw = re.compile(r"\b(chaotic|messy|hack|sloppy|broken|ugly)\b", re.I)

        if beauty_kw.search(prompt):
            score = min(score + 0.10, 1.0)
            rationale_parts.append("Beauty/intentional design signals present.")

        if chaos_kw.search(prompt):
            score -= 0.10
            rationale_parts.append("Incoherence/chaos signals detected.")

        rationale = " ".join(rationale_parts) or "Neutral beauty signal."
        return max(0.0, min(score, 1.0)), rationale


# ── Engine ─────────────────────────────────────────────────────────────────────

class LoveQualityEngine:
    """
    Aggregates 7-agent outputs and prompt text into a composite LQ score.
    """

    _RUBRICS = {
        "flourishing":    _Rubric.flourishing,
        "harm_reduction": _Rubric.harm_reduction,
        "equity":         _Rubric.equity,
        "regenerative":   _Rubric.regenerative,
        "cooperation":    _Rubric.cooperation,
        "beauty":         _Rubric.beauty,
    }

    def score(self, prompt: str, agent_outputs: dict) -> LQScore:
        # Sanitise inputs
        if not isinstance(prompt, str):
            prompt = str(prompt) if prompt is not None else ""
        if not isinstance(agent_outputs, dict):
            agent_outputs = {}

        dimensions: list[DimensionScore] = []
        composite = 0.0

        for dim_name, weight in WEIGHTS.items():
            rubric_fn = self._RUBRICS[dim_name]
            raw, rationale = rubric_fn(prompt, agent_outputs)
            weighted = raw * weight
            composite += weighted
            dimensions.append(
                DimensionScore(
                    name=dim_name,
                    weight=weight,
                    raw_score=raw,
                    weighted_score=weighted,
                    rationale=rationale,
                )
            )

        passed = composite >= LQ_THRESHOLD
        rejection_reason = (
            None
            if passed
            else (
                f"Composite LQ score {composite:.3f} is below required threshold "
                f"{LQ_THRESHOLD}. Action blocked and returned for revision."
            )
        )

        return LQScore(
            composite=composite,
            passed=passed,
            dimensions=dimensions,
            rejection_reason=rejection_reason,
        )