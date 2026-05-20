//! Aethel Safety Kernel — standalone binary entry point.
//! Reads a JSON request from stdin, runs the 3-gate pipeline, writes JSON to stdout.
//!
//! Input JSON schema:
//!   { "human_consent": bool, "lq_score": f64, "action_text": string }
//!
//! Output JSON schema:
//!   { "verdict": "APPROVED"|"BLOCKED", "blocked_at_gate": int|null,
//!     "reason": string|null, "gates": [...] }

mod aethel_safety_kernel;
use aethel_safety_kernel::AethelKernel;

use std::io::{self, Read};

fn main() {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).expect("Failed to read stdin");

    let req: serde_json::Value =
        serde_json::from_str(&input).expect("Invalid JSON input");

    let human_consent = req["human_consent"].as_bool().unwrap_or(false);
    let lq_score      = req["lq_score"].as_f64().unwrap_or(0.0);
    let action_text   = req["action_text"].as_str().unwrap_or("");

    let result = AethelKernel::validate(human_consent, lq_score, action_text);

    let gates_json: Vec<serde_json::Value> = result.gates.iter().map(|g| {
        let (verdict_str, reason_str) = match &g.verdict {
            aethel_safety_kernel::GateVerdict::Pass => ("PASS", None),
            aethel_safety_kernel::GateVerdict::Fail(r) => ("FAIL", Some(r.as_str())),
        };
        serde_json::json!({
            "gate": g.gate_number,
            "name": g.name,
            "verdict": verdict_str,
            "reason": reason_str,
        })
    }).collect();

    let output = serde_json::json!({
        "verdict": result.verdict,
        "blocked_at_gate": result.blocked_at_gate,
        "reason": result.reason,
        "gates": gates_json,
    });

    println!("{}", serde_json::to_string_pretty(&output).unwrap());
}