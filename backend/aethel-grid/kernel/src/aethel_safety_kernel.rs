//! OpenClaw Colony — Aethel Safety Kernel
//! Rust 1.75+ · Memory-safe, deterministic, 3-gate sovereignty validation.
//!
//! Gate 1 — Sovereignty check: explicit human consent must be present.
//! Gate 2 — Love Quality gate: composite LQ score ≥ 0.85 required.
//! Gate 3 — Extraction signature scan: no flagged patterns permitted.
//!
//! All three gates must return PASS for an action to be committed.
//! There is no override path.

use std::collections::HashSet;

// ── Constants ─────────────────────────────────────────────────────────────────

const LQ_THRESHOLD: f64 = 0.85;

/// Extraction signatures that Gate 3 scans for.
/// Any match → BLOCKED, no exceptions.
const EXTRACTION_SIGNATURES: &[&str] = &[
    "private_fork",
    "concentrate_power",
    "surveillance",
    "bypass_consent",
    "override_kernel",
    "skip_gate",
    "redirect_manna",
    "extract_without_consent",
    "unilateral_deploy",
];

// ── Data structures ───────────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq)]
pub enum GateVerdict {
    Pass,
    Fail(String),
}

impl GateVerdict {
    pub fn is_pass(&self) -> bool {
        matches!(self, GateVerdict::Pass)
    }
}

#[derive(Debug, Clone)]
pub struct GateResult {
    pub gate_number: u8,
    pub name: &'static str,
    pub verdict: GateVerdict,
}

#[derive(Debug, Clone)]
pub struct KernelResult {
    pub verdict: &'static str,          // "APPROVED" | "BLOCKED"
    pub gates: [GateResult; 3],
    pub blocked_at_gate: Option<u8>,
    pub reason: Option<String>,
}

impl KernelResult {
    pub fn is_approved(&self) -> bool {
        self.verdict == "APPROVED"
    }
}

// ── Kernel ────────────────────────────────────────────────────────────────────

pub struct AethelKernel;

impl AethelKernel {
    /// Run all three gates sequentially.
    /// Execution stops at the first failing gate.
    pub fn validate(
        human_consent: bool,
        lq_score: f64,
        action_text: &str,
    ) -> KernelResult {
        // Gate 1 — Sovereignty
        let gate1 = Self::gate1_sovereignty(human_consent);
        if !gate1.verdict.is_pass() {
            let reason = match &gate1.verdict {
                GateVerdict::Fail(r) => r.clone(),
                _ => unreachable!(),
            };
            return KernelResult {
                verdict: "BLOCKED",
                gates: [
                    gate1,
                    GateResult {
                        gate_number: 2,
                        name: "Love Quality Gate",
                        verdict: GateVerdict::Fail("Not reached — blocked at Gate 1".into()),
                    },
                    GateResult {
                        gate_number: 3,
                        name: "Extraction Signature Scan",
                        verdict: GateVerdict::Fail("Not reached — blocked at Gate 1".into()),
                    },
                ],
                blocked_at_gate: Some(1),
                reason: Some(reason),
            };
        }

        // Gate 2 — Love Quality
        let gate2 = Self::gate2_love_quality(lq_score);
        if !gate2.verdict.is_pass() {
            let reason = match &gate2.verdict {
                GateVerdict::Fail(r) => r.clone(),
                _ => unreachable!(),
            };
            return KernelResult {
                verdict: "BLOCKED",
                gates: [
                    gate1,
                    gate2,
                    GateResult {
                        gate_number: 3,
                        name: "Extraction Signature Scan",
                        verdict: GateVerdict::Fail("Not reached — blocked at Gate 2".into()),
                    },
                ],
                blocked_at_gate: Some(2),
                reason: Some(reason),
            };
        }

        // Gate 3 — Extraction signature scan
        let gate3 = Self::gate3_extraction_scan(action_text);
        if !gate3.verdict.is_pass() {
            let reason = match &gate3.verdict {
                GateVerdict::Fail(r) => r.clone(),
                _ => unreachable!(),
            };
            return KernelResult {
                verdict: "BLOCKED",
                gates: [gate1, gate2, gate3],
                blocked_at_gate: Some(3),
                reason: Some(reason),
            };
        }

        // All gates passed
        KernelResult {
            verdict: "APPROVED",
            gates: [gate1, gate2, gate3],
            blocked_at_gate: None,
            reason: None,
        }
    }

    // ── Gate implementations ──────────────────────────────────────────────────

    fn gate1_sovereignty(human_consent: bool) -> GateResult {
        let verdict = if human_consent {
            GateVerdict::Pass
        } else {
            GateVerdict::Fail(
                "Gate 1 FAIL: No explicit human consent present. \
                 Sovereignty requires human-in-the-loop confirmation before any action is committed."
                    .into(),
            )
        };
        GateResult {
            gate_number: 1,
            name: "Sovereignty Check",
            verdict,
        }
    }

    fn gate2_love_quality(lq_score: f64) -> GateResult {
        let verdict = if lq_score >= LQ_THRESHOLD {
            GateVerdict::Pass
        } else {
            GateVerdict::Fail(format!(
                "Gate 2 FAIL: LQ score {:.4} is below required threshold {:.2}. \
                 Action must be revised until it meets the Love Quality standard.",
                lq_score, LQ_THRESHOLD
            ))
        };
        GateResult {
            gate_number: 2,
            name: "Love Quality Gate",
            verdict,
        }
    }

    fn gate3_extraction_scan(action_text: &str) -> GateResult {
        let lower = action_text.to_lowercase();
        let found: Vec<&str> = EXTRACTION_SIGNATURES
            .iter()
            .copied()
            .filter(|sig| lower.contains(sig))
            .collect();

        let verdict = if found.is_empty() {
            GateVerdict::Pass
        } else {
            GateVerdict::Fail(format!(
                "Gate 3 FAIL: Extraction signatures detected: {:?}. \
                 No action containing extraction patterns may be committed.",
                found
            ))
        };
        GateResult {
            gate_number: 3,
            name: "Extraction Signature Scan",
            verdict,
        }
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    // ── Scenario 1: Clean task — all gates pass ───────────────────────────────
    #[test]
    fn sovereignty_check() {
        // Gate 1 pass: consent = true
        let result = AethelKernel::validate(true, 0.92, "Help structure a community grant application.");
        assert!(result.gates[0].verdict.is_pass(), "Gate 1 should pass with consent=true");
    }

    // ── Scenario 2: LQ gate ───────────────────────────────────────────────────
    #[test]
    fn love_quality_gate() {
        // Gate 2 pass: LQ ≥ 0.85
        let pass = AethelKernel::validate(true, 0.90, "Regenerative community design proposal.");
        assert!(pass.gates[1].verdict.is_pass(), "Gate 2 should pass with LQ=0.90");

        // Gate 2 fail: LQ < 0.85
        let fail = AethelKernel::validate(true, 0.70, "Some low-quality action.");
        assert!(!fail.gates[1].verdict.is_pass(), "Gate 2 should fail with LQ=0.70");
        assert_eq!(fail.blocked_at_gate, Some(2));
    }

    // ── Scenario 3: Extraction scan ───────────────────────────────────────────
    #[test]
    fn extraction_scan() {
        // Gate 3 fail: extraction signature present
        let result = AethelKernel::validate(
            true,
            0.91,
            "Deploy module with private_fork of community ledger.",
        );
        assert!(!result.gates[2].verdict.is_pass(), "Gate 3 should fail on extraction signature");
        assert_eq!(result.blocked_at_gate, Some(3));
        assert_eq!(result.verdict, "BLOCKED");
    }

    // ── Scenario 4: No consent — blocked at Gate 1 ───────────────────────────
    #[test]
    fn no_consent_blocked() {
        let result = AethelKernel::validate(false, 0.95, "Any action without consent.");
        assert_eq!(result.verdict, "BLOCKED");
        assert_eq!(result.blocked_at_gate, Some(1));
        assert!(!result.gates[0].verdict.is_pass());
    }

    // ── Scenario 5: Full pipeline — approved ─────────────────────────────────
    #[test]
    fn full_pipeline() {
        let result = AethelKernel::validate(
            true,
            0.88,
            "Community governance proposal: equitable resource allocation for NODE-601.",
        );
        assert_eq!(result.verdict, "APPROVED");
        assert!(result.blocked_at_gate.is_none());
        assert!(result.gates.iter().all(|g| g.verdict.is_pass()));
    }
}