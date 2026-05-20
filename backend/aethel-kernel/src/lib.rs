//! OpenClaw Colony — Aethel Safety Kernel
//! ========================================
//! Native Rust implementation of the 4-gate validation pipeline + SHA-256
//! lineage chaining, exposed to Python via PyO3.
//!
//! Architecture
//! ------------
//!   Python coordinator  →  FFI boundary  →  Rust kernel
//!                                              ├── Gate 0: Biometric HMAC verify
//!                                              ├── Gate 1: Human consent
//!                                              ├── Gate 2: LQ threshold (≥ 0.85)
//!                                              ├── Gate 3: Extraction signature scan
//!                                              └── Lineage: SHA-256 chain commit
//!                          FFI boundary  ←  GateResponse { approved, gate, reason,
//!                                                           new_lineage_hash }
//!
//! Security properties
//! -------------------
//!   • All HMAC comparisons use constant-time `verify_slice` (no timing leaks)
//!   • Raw biometric bytes never cross the FFI — only the HMAC token string
//!   • Lineage hash computed atomically with gate result (no Python gap)
//!   • Gate 3 regex patterns compiled once at module load (no re-compilation)
//!   • `panic = "abort"` in release profile — no unwinding across FFI boundary

use std::time::{SystemTime, UNIX_EPOCH};

use hmac::{Hmac, Mac};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use regex::RegexSet;
use sha2::{Digest, Sha256};

type HmacSha256 = Hmac<Sha256>;

// ── Attestation token TTL ─────────────────────────────────────────────────────
const ATTESTATION_TTL_SECS: u64 = 90;

// ── LQ composite threshold ────────────────────────────────────────────────────
const LQ_THRESHOLD: f64 = 0.85;

// ── Gate 3 extraction signatures ─────────────────────────────────────────────
// Compiled once at module load via std::sync::OnceLock.
static EXTRACTION_PATTERNS: std::sync::OnceLock<RegexSet> = std::sync::OnceLock::new();

fn extraction_patterns() -> &'static RegexSet {
    EXTRACTION_PATTERNS.get_or_init(|| {
        RegexSet::new([
            // Direct treasury bypass attempts
            r"(?i)bypass[_\-\s]?treasury",
            r"(?i)extraction[_\-\s]?vector",
            // Multi-sig bypass
            r"(?i)multisig[_\-\s]?bypass",
            r"(?i)skip[_\-\s]?gate",
            // Hidden balance modification
            r"(?i)shadow[_\-\s]?balance",
            r"(?i)secondary[_\-\s]?ledger",
            r"(?i)hidden[_\-\s]?transfer",
            // Covert exfiltration
            r"(?i)exfil(?:trate)?",
            r"(?i)covert[_\-\s]?channel",
            r"(?i)side[_\-\s]?channel[_\-\s]?transfer",
            // Rug-pull patterns
            r"(?i)drain[_\-\s]?pool",
            r"(?i)rug[_\-\s]?pull",
            r"(?i)liquidity[_\-\s]?drain",
            // Governance manipulation
            r"(?i)vote[_\-\s]?stuff",
            r"(?i)quorum[_\-\s]?bypass",
            r"(?i)consensus[_\-\s]?override",
            // Biometric spoofing signals
            r"(?i)spoof[_\-\s]?biometric",
            r"(?i)replay[_\-\s]?token",
            r"(?i)forge[_\-\s]?attestation",
            // Legacy Python-fallback patterns (kept for backward compatibility)
            r"(?i)private[_\-\s]?fork",
            r"(?i)concentrate[_\-\s]?power",
            r"(?i)surveillance",
            r"(?i)bypass[_\-\s]?consent",
            r"(?i)override[_\-\s]?kernel",
            r"(?i)redirect[_\-\s]?manna",
            r"(?i)extract[_\-\s]?without[_\-\s]?consent",
            r"(?i)unilateral[_\-\s]?deploy",
        ])
        .expect("Extraction pattern compilation failed — this is a build-time error")
    })
}

// ─────────────────────────────────────────────────────────────────────────────
// Data structures
// ─────────────────────────────────────────────────────────────────────────────

/// Payload passed from Python coordinator into the kernel.
///
/// `token_hmac` format:  `<hex-payload>.<hex-signature>`
///   where payload is a JSON object containing at minimum:
///     { "issued_at": <unix_timestamp_secs>, "member_id": "<uuid>" }
#[pyclass]
#[derive(Clone)]
pub struct TransactionPayload {
    /// Unique task identifier (included in lineage hash)
    #[pyo3(get, set)]
    pub task_id: String,

    /// Biometric attestation token: `<payload_hex>.<hmac_hex>`
    #[pyo3(get, set)]
    pub token_hmac: String,

    /// Explicit human-in-the-loop consent flag
    #[pyo3(get, set)]
    pub human_consent: bool,

    /// Composite Love Quality score (0.0 – 1.0)
    #[pyo3(get, set)]
    pub lq_score: f64,

    /// Serialised agent output strings (scanned for extraction signatures)
    #[pyo3(get, set)]
    pub agent_outputs: Vec<String>,

    /// Previous lineage hash (hex string or "GENESIS")
    #[pyo3(get, set)]
    pub previous_lineage_hash: String,

    /// Actor member_id extracted from biometric token (set by coordinator)
    #[pyo3(get, set)]
    pub actor_id: String,

    /// Action type string (must appear in token's action_scope)
    #[pyo3(get, set)]
    pub action_type: String,
}

#[pymethods]
impl TransactionPayload {
    #[new]
    #[pyo3(signature = (
        task_id,
        token_hmac,
        human_consent,
        lq_score,
        agent_outputs,
        previous_lineage_hash,
        actor_id = String::new(),
        action_type = "proposal".to_string(),
    ))]
    fn new(
        task_id: String,
        token_hmac: String,
        human_consent: bool,
        lq_score: f64,
        agent_outputs: Vec<String>,
        previous_lineage_hash: String,
        actor_id: String,
        action_type: String,
    ) -> Self {
        TransactionPayload {
            task_id,
            token_hmac,
            human_consent,
            lq_score,
            agent_outputs,
            previous_lineage_hash,
            actor_id,
            action_type,
        }
    }
}

/// Result returned to Python after kernel execution.
#[pyclass]
pub struct GateResponse {
    /// True iff all four gates passed
    #[pyo3(get)]
    pub approved: bool,

    /// Index of the gate that blocked (0–3), or None if approved
    #[pyo3(get)]
    pub failed_gate: Option<u8>,

    /// Human-readable reason string
    #[pyo3(get)]
    pub reason: String,

    /// New lineage hash (hex) — always computed, even on block
    /// (blocked actions are chained too — they are part of the record)
    #[pyo3(get)]
    pub new_lineage_hash: String,

    /// Unix timestamp (seconds) when kernel executed
    #[pyo3(get)]
    pub kernel_timestamp: u64,
}

#[pymethods]
impl GateResponse {
    fn __repr__(&self) -> String {
        format!(
            "GateResponse(approved={}, failed_gate={:?}, reason={:?}, lineage={}...)",
            self.approved,
            self.failed_gate,
            self.reason,
            &self.new_lineage_hash[..16],
        )
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Gate implementations
// ─────────────────────────────────────────────────────────────────────────────

/// Gate 0: Biometric attestation HMAC verification + TTL check.
///
/// Token format: `<payload_hex>.<signature_hex>`
///   payload_hex  = hex-encoded JSON bytes
///   signature_hex = hex-encoded HMAC-SHA256 over payload_hex bytes
///
/// Checks:
///   1. Token is structurally valid (two dot-separated parts)
///   2. HMAC signature matches (constant-time comparison)
///   3. Token was issued within the last ATTESTATION_TTL_SECS seconds
///   4. Token is not from the future (clock skew ≤ 5 seconds allowed)
fn verify_gate_0(token_hmac: &str, secret: &[u8]) -> Result<(), String> {
    // 1. Structural check
    let parts: Vec<&str> = token_hmac.splitn(2, '.').collect();
    if parts.len() != 2 {
        return Err("GATE0_MALFORMED: Token envelope structural anomaly — expected payload.signature".to_string());
    }

    let payload_hex = parts[0];
    let sig_hex     = parts[1];

    // 2. Decode signature
    let sig_bytes = hex::decode(sig_hex)
        .map_err(|_| "GATE0_MALFORMED: Signature is not valid hex".to_string())?;

    // 3. Constant-time HMAC verification
    let mut mac = HmacSha256::new_from_slice(secret)
        .map_err(|_| "GATE0_CONFIG: Invalid HSM secret key length".to_string())?;
    mac.update(payload_hex.as_bytes());
    mac.verify_slice(&sig_bytes)
        .map_err(|_| "GATE0_INVALID_SIG: Biometric attestation signature mismatch — potential spoof detected".to_string())?;

    // 4. Decode payload and check TTL
    let payload_bytes = hex::decode(payload_hex)
        .map_err(|_| "GATE0_MALFORMED: Payload is not valid hex".to_string())?;
    let payload_str = std::str::from_utf8(&payload_bytes)
        .map_err(|_| "GATE0_MALFORMED: Payload is not valid UTF-8".to_string())?;

    // Parse issued_at from JSON (minimal parse — avoid full serde for speed)
    let issued_at = extract_issued_at(payload_str)
        .ok_or_else(|| "GATE0_MALFORMED: Token missing issued_at field".to_string())?;

    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "GATE0_CLOCK: System clock error".to_string())?
        .as_secs();

    // Future token (clock skew > 5s)
    if issued_at > now + 5 {
        return Err(format!(
            "GATE0_FUTURE: Token issued_at ({}) is in the future (now={})",
            issued_at, now
        ));
    }

    // Expired token
    let age = now.saturating_sub(issued_at);
    if age > ATTESTATION_TTL_SECS {
        return Err(format!(
            "GATE0_EXPIRED: Token age {}s exceeds TTL {}s",
            age, ATTESTATION_TTL_SECS
        ));
    }

    Ok(())
}

/// Extract `issued_at` unix timestamp from a JSON string without full serde.
///
/// Searches for the pattern `"issued_at"` followed by optional whitespace, a
/// colon, optional whitespace, and then a run of ASCII digits.  To avoid false
/// positives where the string `"issued_at"` appears as a *value* inside another
/// field (e.g. `"label": "issued_at"`), we require that the match is preceded
/// by either the start of the string, a `{`, or a `,` (after stripping
/// whitespace) — i.e. it must be in key position.
fn extract_issued_at(json: &str) -> Option<u64> {
    let key = "\"issued_at\"";
    let mut search_start = 0;

    loop {
        // Find next occurrence of the key string
        let rel_pos = json[search_start..].find(key)?;
        let pos = search_start + rel_pos;

        // Verify the character immediately before the key (ignoring whitespace)
        // is a valid JSON key-position delimiter: start-of-object '{' or
        // value-separator ','.  This rejects occurrences inside string values.
        let before = json[..pos].trim_end();
        let is_key_position = before.is_empty()
            || before.ends_with('{')
            || before.ends_with(',');

        if is_key_position {
            let after_key = &json[pos + key.len()..];
            // Skip optional whitespace then colon
            if let Some(after_colon) = after_key.trim_start().strip_prefix(':') {
                let trimmed = after_colon.trim_start();
                // Read digits
                let digits: String = trimmed
                    .chars()
                    .take_while(|c| c.is_ascii_digit())
                    .collect();
                if !digits.is_empty() {
                    return digits.parse().ok();
                }
            }
        }

        // This occurrence was not in key position — keep searching
        search_start = pos + key.len();
        if search_start >= json.len() {
            return None;
        }
    }
}

/// Gate 1: Explicit human consent flag.
fn verify_gate_1(human_consent: bool) -> Result<(), String> {
    if !human_consent {
        return Err("GATE1_NO_CONSENT: Human-in-the-loop validation flag missing or false".to_string());
    }
    Ok(())
}

/// Gate 2: Love Quality composite score threshold.
///
/// Valid range: [0.0, 1.0] finite float, and must be >= LQ_THRESHOLD (0.85).
/// Rejects: NaN, Inf, scores < 0.0, scores > 1.0, and scores < LQ_THRESHOLD.
fn verify_gate_2(lq_score: f64) -> Result<(), String> {
    if !lq_score.is_finite() {
        return Err(format!(
            "GATE2_INVALID_SCORE: LQ score is not finite ({})",
            lq_score
        ));
    }
    if lq_score < 0.0 || lq_score > 1.0 {
        return Err(format!(
            "GATE2_INVALID_SCORE: LQ score {:.4} is outside valid probability range [0.0, 1.0]",
            lq_score
        ));
    }
    if lq_score < LQ_THRESHOLD {
        return Err(format!(
            "GATE2_LQ_SUBTHRESHOLD: Value Equilibrium Consensus sub-threshold: score={:.4} < required={:.2}",
            lq_score, LQ_THRESHOLD
        ));
    }
    Ok(())
}

/// Gate 3: Extraction signature scan across all agent outputs.
///
/// Returns an error naming the first matched pattern text so that audit logs
/// and test assertions can identify which signature triggered the block.
fn verify_gate_3(agent_outputs: &[String]) -> Result<(), String> {
    // Pattern display names — must stay in sync with the RegexSet order above.
    const PATTERN_NAMES: &[&str] = &[
        "bypass_treasury", "extraction_vector",
        "multisig_bypass", "skip_gate",
        "shadow_balance", "secondary_ledger", "hidden_transfer",
        "exfiltrate", "covert_channel", "side_channel_transfer",
        "drain_pool", "rug_pull", "liquidity_drain",
        "vote_stuff", "quorum_bypass", "consensus_override",
        "spoof_biometric", "replay_token", "forge_attestation",
        "private_fork", "concentrate_power", "surveillance",
        "bypass_consent", "override_kernel", "redirect_manna",
        "extract_without_consent", "unilateral_deploy",
    ];

    let patterns = extraction_patterns();
    for (i, output) in agent_outputs.iter().enumerate() {
        let matched_indices: Vec<usize> = patterns.matches(output).into_iter().collect();
        if !matched_indices.is_empty() {
            let names: Vec<&str> = matched_indices
                .iter()
                .filter_map(|&idx| PATTERN_NAMES.get(idx).copied())
                .collect();
            let display = if names.is_empty() {
                format!("pattern indices: {:?}", matched_indices)
            } else {
                names.join(", ")
            };
            return Err(format!(
                "GATE3_EXTRACTION_SIG: Malicious extraction signature detected in agent output [{}] — matched: {}",
                i, display
            ));
        }
    }
    Ok(())
}

// ─────────────────────────────────────────────────────────────────────────────
// Lineage chaining
// ─────────────────────────────────────────────────────────────────────────────

/// Compute the next lineage hash.
///
/// Hash input: SHA-256( previous_hash || task_id || actor_id || outcome || timestamp )
/// All fields are length-prefixed to prevent collision attacks.
fn compute_lineage_hash(
    previous_hash: &str,
    task_id: &str,
    actor_id: &str,
    outcome: &str,
    timestamp: u64,
) -> String {
    let mut hasher = Sha256::new();

    // Length-prefix each field to prevent concatenation collisions
    hasher.update((previous_hash.len() as u32).to_be_bytes());
    hasher.update(previous_hash.as_bytes());

    hasher.update((task_id.len() as u32).to_be_bytes());
    hasher.update(task_id.as_bytes());

    hasher.update((actor_id.len() as u32).to_be_bytes());
    hasher.update(actor_id.as_bytes());

    hasher.update((outcome.len() as u32).to_be_bytes());
    hasher.update(outcome.as_bytes());

    hasher.update(timestamp.to_be_bytes());

    hex::encode(hasher.finalize())
}

// ─────────────────────────────────────────────────────────────────────────────
// Utility pyfunction exports
// ─────────────────────────────────────────────────────────────────────────────

/// Compute a standalone lineage hash (utility function for Python coordinator).
/// Used when Python needs to verify or extend the chain without running gates.
#[pyfunction]
pub fn compute_chain_hash(
    previous_hash: &str,
    task_id: &str,
    actor_id: &str,
    outcome: &str,
    timestamp: u64,
) -> String {
    compute_lineage_hash(previous_hash, task_id, actor_id, outcome, timestamp)
}

/// Verify a biometric token HMAC **and** TTL.
///
/// Calls the full `verify_gate_0` check, which includes:
///   1. Structural validation (payload.signature format)
///   2. Constant-time HMAC-SHA256 signature verification
///   3. TTL check: token must have been issued within the last
///      `ATTESTATION_TTL_SECS` seconds (currently 90 s)
///   4. Future-token check: issued_at must not be more than 5 s in the future
///
/// Returns `true` if all checks pass, `false` otherwise.
/// Use `verify_safety_kernel` for the full 4-gate pipeline.
#[pyfunction]
pub fn verify_token_hmac(token_hmac: &str, secret_key: Vec<u8>) -> PyResult<bool> {
    match verify_gate_0(token_hmac, &secret_key) {
        Ok(_)  => Ok(true),
        Err(_) => Ok(false),
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Main kernel entry point
// ─────────────────────────────────────────────────────────────────────────────

/// Execute the full 4-gate Aethel Safety Kernel.
///
/// This is the single FFI entry point. Python passes a `TransactionPayload`
/// and the HSM secret key bytes. The kernel runs all four gates sequentially,
/// computes the lineage hash (regardless of outcome), and returns a
/// `GateResponse`.
///
/// The lineage hash is computed even on block — rejected actions are part of
/// the permanent record and must be chained.
#[pyfunction]
pub fn verify_safety_kernel(
    payload: TransactionPayload,
    secret_key: Vec<u8>,
) -> PyResult<GateResponse> {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| PyValueError::new_err(format!("Clock error: {}", e)))?
        .as_secs();

    // ── Gate 0: Biometric attestation ────────────────────────────────────────
    if let Err(reason) = verify_gate_0(&payload.token_hmac, &secret_key) {
        let lineage = compute_lineage_hash(
            &payload.previous_lineage_hash,
            &payload.task_id,
            &payload.actor_id,
            &format!("BLOCKED_GATE0:{}", reason),
            now,
        );
        return Ok(GateResponse {
            approved: false,
            failed_gate: Some(0),
            reason,
            new_lineage_hash: lineage,
            kernel_timestamp: now,
        });
    }

    // ── Gate 1: Human consent ─────────────────────────────────────────────────
    if let Err(reason) = verify_gate_1(payload.human_consent) {
        let lineage = compute_lineage_hash(
            &payload.previous_lineage_hash,
            &payload.task_id,
            &payload.actor_id,
            &format!("BLOCKED_GATE1:{}", reason),
            now,
        );
        return Ok(GateResponse {
            approved: false,
            failed_gate: Some(1),
            reason,
            new_lineage_hash: lineage,
            kernel_timestamp: now,
        });
    }

    // ── Gate 2: Love Quality threshold ────────────────────────────────────────
    if let Err(reason) = verify_gate_2(payload.lq_score) {
        let lineage = compute_lineage_hash(
            &payload.previous_lineage_hash,
            &payload.task_id,
            &payload.actor_id,
            &format!("BLOCKED_GATE2:{}", reason),
            now,
        );
        return Ok(GateResponse {
            approved: false,
            failed_gate: Some(2),
            reason,
            new_lineage_hash: lineage,
            kernel_timestamp: now,
        });
    }

    // ── Gate 3: Extraction signature scan ─────────────────────────────────────
    if let Err(reason) = verify_gate_3(&payload.agent_outputs) {
        let lineage = compute_lineage_hash(
            &payload.previous_lineage_hash,
            &payload.task_id,
            &payload.actor_id,
            &format!("BLOCKED_GATE3:{}", reason),
            now,
        );
        return Ok(GateResponse {
            approved: false,
            failed_gate: Some(3),
            reason,
            new_lineage_hash: lineage,
            kernel_timestamp: now,
        });
    }

    // ── All gates passed — compute approval lineage hash ─────────────────────
    let lineage = compute_lineage_hash(
        &payload.previous_lineage_hash,
        &payload.task_id,
        &payload.actor_id,
        "APPROVED",
        now,
    );

    Ok(GateResponse {
        approved: true,
        failed_gate: None,
        reason: "Kernel execution verified. All invariants intact. MANNA authorized.".to_string(),
        new_lineage_hash: lineage,
        kernel_timestamp: now,
    })
}

// ─────────────────────────────────────────────────────────────────────────────
// PyO3 module registration
// ─────────────────────────────────────────────────────────────────────────────

#[pymodule]
fn aethel_kernel(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(verify_safety_kernel, m)?)?;
    m.add_function(wrap_pyfunction!(compute_chain_hash, m)?)?;
    m.add_function(wrap_pyfunction!(verify_token_hmac, m)?)?;
    m.add_class::<TransactionPayload>()?;
    m.add_class::<GateResponse>()?;
    m.add("__version__", "0.7.0")?;
    m.add("LQ_THRESHOLD", LQ_THRESHOLD)?;
    m.add("ATTESTATION_TTL_SECS", ATTESTATION_TTL_SECS as u64)?;
    Ok(())
}
