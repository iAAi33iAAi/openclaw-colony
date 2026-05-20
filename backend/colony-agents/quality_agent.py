"""
OpenClaw Colony — Agent 6: Quality
Governance, safety validation, compliance, and Love Quality pre-screening.
"""

import asyncio
from .base_agent import BaseAgent


class QualityAgent(BaseAgent):
    name = "Quality"
    domain = "Governance, safety validation, and compliance"

    # Extraction signatures that trigger hard blocks
    EXTRACTION_SIGNATURES = [
        "private_fork",
        "concentrate_power",
        "surveillance",
        "bypass_consent",
        "override_kernel",
        "skip_gate",
        "redirect_manna",
    ]

    async def initialize(self):
        self._ready = True

    async def evaluate(self, prompt: str) -> dict:
        await asyncio.sleep(0)
        p = prompt.lower()
        flags = []
        recommendations = []
        governance_score = 0.92

        # Hard extraction-signature scan (mirrors Aethel Gate 3 at agent level)
        detected_signatures = [sig for sig in self.EXTRACTION_SIGNATURES if sig in p]
        if detected_signatures:
            flags.append(f"extraction_signatures_detected: {detected_signatures}")
            governance_score -= 0.50

        # Positive governance signals
        if any(kw in p for kw in ["consent", "sovereign", "audit", "transparent"]):
            recommendations.append("Sovereignty and consent signals present — reinforce in output.")
            governance_score = min(governance_score + 0.03, 1.0)

        if any(kw in p for kw in ["govern", "policy", "compliance", "regulation"]):
            recommendations.append(
                "Embed policy-as-code checks; log all compliance decisions to lineage."
            )

        if any(kw in p for kw in ["safety", "harm", "risk", "danger"]):
            recommendations.append(
                "Trigger harm-reduction review; require explicit human sign-off before commit."
            )
            governance_score = max(governance_score - 0.05, 0.0)

        # LQ pre-screen advisory
        lq_advisory = "Pre-screen LQ estimate: "
        if governance_score >= 0.85:
            lq_advisory += "likely to pass LQ threshold."
        else:
            lq_advisory += "WARNING — may fall below LQ 0.85 threshold; revision recommended."
        recommendations.append(lq_advisory)

        summary = (
            f"Governance score: {governance_score:.2f}. "
            f"Extraction signatures: {detected_signatures or 'none'}. "
            f"Flags: {flags or 'none'}. "
            f"Recommendations: {recommendations}."
        )

        return {
            "agent": self.name,
            "domain": self.domain,
            "summary": summary,
            "governance_score": governance_score,
            "extraction_signatures_found": detected_signatures,
            "flags": flags,
            "recommendations": recommendations,
        }