# Test Suite Map
## Full-Stack Technical Audit — Deliverable 7 of 8

---

## Summary

| Metric | Value |
|--------|-------|
| Total tests | 728 |
| Passing | 728 |
| Failing | 0 |
| Test files | 10 |
| Coverage target | 70% |

---

## Test File Inventory

### test_aethel_kernel_rust.py (71 tests) — UNIT + INTEGRATION
**Category:** Cryptographic gate tests
**Covers:**
- Gate 0: HMAC verification, TTL, future tokens, malformed tokens
- Gate 1: consent flag
- Gate 2: LQ bounds, threshold, NaN/Inf rejection
- Gate 3: all 27 extraction patterns, case variants
- Lineage hash: determinism, length-prefix collision resistance
- PyO3 FFI: type coercion, error propagation
- Concurrent gate evaluations (50 threads)

**Gaps:** No fuzzing, no property-based tests

---

### test_biometric.py — UNIT + INTEGRATION
**Category:** Gate 0 biometric validation
**Covers:**
- Token issuance and verification
- TTL expiry (90s boundary)
- Single-use enforcement
- Member enrollment (3-witness requirement)
- Liveness score threshold
- Cooling-off windows by MANNA amount
- Duress detection
- Revocation events

**Gaps:** No hardware scanner simulation

---

### test_state_machine.py (56 tests) — UNIT
**Category:** Deterministic state transitions
**Covers:**
- NodeState: all valid transitions
- NodeState: all invalid transitions rejected
- SYNCING→LIVE lineage head check guard
- Isolation detection
- Observer pattern (callbacks)
- Thread safety (concurrent transitions)
- ProposalState: terminal states
- Proposal expiry background task
- TransactionState: full approved path
- TransactionState: blocked at each gate
- Chain lock (atomic lineage writes)
- Transition table completeness

**Gaps:** No network partition simulation

---

### test_federation.py — INTEGRATION
**Category:** Gossip, proposals, quorum voting
**Covers:**
- Peer announcement and registration
- Lineage tip gossip
- Cross-node proposal creation
- Vote recording and quorum calculation
- Proposal approval and blocking
- Federation status endpoint
- Heartbeat endpoint

**Gaps:** No multi-node integration test, no Byzantine fault test

---

### test_colony_chaos.py — ADVERSARIAL
**Category:** Latency spikes, corrupt payloads, Byzantine faults
**Covers:**
- Malformed token envelopes
- Injected extraction signatures
- Concurrent adversarial submissions
- Split-signal strategies
- Coalition attacks (alternating clean/malicious)
- Timing boundary conditions
- Type injection attacks

**Gaps:** No actual network chaos (Toxiproxy integration)

---

### test_colony_extended.py (83 tests) — INTEGRATION
**Category:** Full pipeline scenarios
**Covers:**
- End-to-end approved transactions
- End-to-end blocked transactions
- LQ score boundary conditions
- Agent output variations
- Lineage chain growth

---

### test_colony_advanced.py — INTEGRATION
**Category:** Advanced scenarios
**Covers:**
- Bytes objects in agent outputs (Gap fixed in v0.7.1)
- Complex nested extraction signatures
- Edge cases in type coercion

---

### test_colony.py (195 tests) — UNIT + INTEGRATION
**Category:** Baseline validation
**Covers:**
- LQ engine dimension weights
- LQ engine scoring rubrics
- 5 core scenarios (approved + blocked)
- Agent pipeline execution

---

### test_dev_commit_init.py (39 tests) — UNIT
**Category:** Genesis idempotency
**Covers:**
- Secret validation (strict + dev mode)
- Genesis block creation
- Genesis hash determinism
- Commit genesis (fresh + idempotent)
- Full dev_commit_init() integration
- State machine wiring
- Table initialization failure handling

---

### test_covenant.py (23 tests) — CONSTITUTIONAL
**Category:** Invariant enforcement
**Covers:**
- MANNA 1% split at any scale
- Splits sum to total
- Gate pipeline sequentiality
- No gate skipping
- APPROVED only from GATE_3_CHECK
- CHAINED is terminal
- 27 extraction signatures present
- LQ threshold is exactly 0.85
- bypass_treasury always blocked
- No consent always blocked
- Low LQ always blocked
- Genesis anchored to 64 zeros
- Genesis LQ is 1.0
- SYNCING→LIVE requires lineage check
- All node states have transitions
- Terminal proposal states are final
- Covenant fingerprint stability
- Proof of Covenant generation

---

## Coverage Gaps

| Area | Gap | Priority |
|------|-----|----------|
| CI/CD | No GitHub Actions running (workflow scope) | CRITICAL |
| Agents | No tests for individual agent evaluate() | HIGH |
| Frontend | No UI tests | HIGH |
| API | No OpenAPI contract tests | HIGH |
| Stripe | Limited webhook tests | MEDIUM |
| Federation | No multi-node integration | HIGH |
| Fuzzing | No cargo fuzz targets | MEDIUM |
| Performance | No benchmark suite | MEDIUM |
| Load | No load tests | MEDIUM |

---

## Test Execution

```bash
cd backend
pip install -r requirements.txt

# Build Rust kernel first
cd aethel-kernel
maturin build --release
pip install target/wheels/*.whl
cd ..

# Run all tests
pytest ../tests/ -v

# Run only constitutional tests
pytest ../tests/test_covenant.py -v

# Run with coverage
pytest ../tests/ --cov=. --cov-report=html
```

---

## CI Status

GitHub Actions workflow exists at `.github/workflows/ci.yml`.
**Status:** Not yet running — requires `workflow` token scope to push.

Once active, CI runs on every push to `main`:
- vector-safety (Rust build + invariant checks)
- vector-access (installer validation)
- vector-sovereignty (dependency audit)
- test-suite (728 tests)
- spec-drift (ADR presence check)
- telemetry-baseline (metrics report)
