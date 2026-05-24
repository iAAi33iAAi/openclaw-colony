# Rust Kernel Boundary Contract
## Full-Stack Technical Audit — Deliverable 2 of 8

---

## FFI Boundary — Inputs

### TransactionPayload (Python → Rust)

| Field | Type | Constraints | Coercion in Python |
|-------|------|-------------|-------------------|
| `task_id` | `String` | Non-empty | `str(task_id)` |
| `token_hmac` | `String` | `<hex>.<hex>` format | None — must be pre-formed |
| `human_consent` | `bool` | True/False | `bool(human_consent)` |
| `lq_score` | `f64` | Finite, [0.0, 1.0] | Non-numeric → -1.0 |
| `agent_outputs` | `Vec<String>` | JSON-serialized | `[json.dumps(outputs)]` |
| `previous_lineage_hash` | `String` | 64 hex chars or "GENESIS" | None |
| `actor_id` | `String` | UUID or empty | From biometric token |
| `action_type` | `String` | "proposal" default | None |

### GateResponse (Rust → Python)

| Field | Type | Meaning |
|-------|------|---------|
| `approved` | `bool` | True iff all 4 gates passed |
| `failed_gate` | `Option<u8>` | 0-3 or None |
| `reason` | `String` | Human-readable failure reason |
| `new_lineage_hash` | `String` | SHA-256 hex — always computed |
| `kernel_timestamp` | `u64` | Unix seconds when kernel ran |

---

## Gate Contracts

### Gate 0 — Biometric Attestation

**Input:** `token_hmac: &str`, `secret: &[u8]`

**Algorithm:**
```
1. Split on '.' → [payload_hex, sig_hex]
2. hex::decode(sig_hex) → sig_bytes
3. HmacSha256::new(secret).update(payload_hex).verify_slice(sig_bytes)
4. hex::decode(payload_hex) → payload_bytes
5. UTF-8 decode → payload_str
6. extract_issued_at(payload_str) → issued_at (key-position validated)
7. now - issued_at ≤ 90s
8. issued_at ≤ now + 5s
```

**Guarantees:**
- Constant-time HMAC comparison (no timing leaks)
- Key-position validation prevents `issued_at` injection via value fields
- TTL prevents replay attacks
- Future-token check prevents clock manipulation

**Error codes:**
- `GATE0_MALFORMED` — structural anomaly
- `GATE0_INVALID_SIG` — HMAC mismatch
- `GATE0_EXPIRED` — token age > 90s
- `GATE0_FUTURE` — issued_at > now + 5s
- `GATE0_CLOCK` — system clock error
- `GATE0_CONFIG` — invalid secret key length

---

### Gate 1 — Human Consent

**Input:** `human_consent: bool`

**Contract:** `human_consent == true` → PASS

**Error:** `GATE1_NO_CONSENT`

---

### Gate 2 — Love Quality Threshold

**Input:** `lq_score: f64`

**Contract:**
```
lq_score.is_finite() == true
AND lq_score >= 0.0
AND lq_score <= 1.0
AND lq_score >= 0.85
```

**Error codes:**
- `GATE2_INVALID_SCORE` — NaN, Inf, or outside [0.0, 1.0]
- `GATE2_LQ_SUBTHRESHOLD` — below 0.85

---

### Gate 3 — Extraction Signature Scan

**Input:** `agent_outputs: &[String]`

**Algorithm:** `OnceLock<RegexSet>` with 27 case-insensitive patterns

**Patterns (27 total):**
```
bypass_treasury      extraction_vector    multisig_bypass
skip_gate            shadow_balance       secondary_ledger
hidden_transfer      exfiltrate           covert_channel
side_channel_transfer drain_pool          rug_pull
liquidity_drain      vote_stuff           quorum_bypass
consensus_override   spoof_biometric      replay_token
forge_attestation    private_fork         concentrate_power
surveillance         bypass_consent       override_kernel
redirect_manna       extract_without_consent unilateral_deploy
```

**Error:** `GATE3_EXTRACTION_SIG: ... matched: <pattern_name>`

---

## Lineage Hash Contract

```
SHA-256(
  u32_be(len(prev_hash)) || prev_hash   ||
  u32_be(len(task_id))   || task_id     ||
  u32_be(len(actor_id))  || actor_id    ||
  u32_be(len(outcome))   || outcome     ||
  u64_be(timestamp)
)
```

**Properties:**
- Length-prefixed fields prevent concatenation collision attacks
- Computed atomically with gate result (no Python gap)
- Computed on EVERY transaction — approved AND blocked
- `outcome` encodes gate failure: `"BLOCKED_GATE0:<reason>"`

---

## Security Properties (By Construction)

| Property | Mechanism |
|----------|-----------|
| No timing attacks | `mac.verify_slice()` constant-time |
| No raw biometric data crosses FFI | Only HMAC token string |
| No panic unwind across FFI | `panic = "abort"` in release |
| No regex recompilation | `OnceLock<RegexSet>` |
| No gate skipping | Sequential early-return |
| No lineage gap | Hash computed inside kernel |

---

## Missing Specs (Gaps to Fill)

| Gap | Priority | Recommended Fix |
|-----|----------|----------------|
| No formal threat model | HIGH | Write `docs/THREAT_MODEL.md` |
| No fuzzing harness | HIGH | Add `cargo fuzz` targets for Gate 0 parser |
| No property-based tests for lineage hash | MEDIUM | Add `proptest` crate |
| No benchmark for gate evaluation latency | MEDIUM | Add `criterion` benchmarks |
| No cross-platform build verification | MEDIUM | Add ARM64 CI target |
| Python fallback not tested against Rust | LOW | Add parity tests |
