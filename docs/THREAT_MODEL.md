# OpenClaw Colony — Threat Model
## Version 1.0 — Node 001 — Bethel Acres

*Cross-reference: GOVERNANCE.md v1.0, PFP-SPEC-2026-001.md, docs/audit/05-SECURITY-BOUNDARY-MAP.md*

---

## Scope

This threat model covers the OpenClaw Colony software system as deployed
on a single node (Node 001 — Bethel Acres) and in federation with peer nodes.

It does not cover physical security of the hardware, network infrastructure
attacks below the application layer, or supply chain attacks on dependencies.

---

## Trust Zones

```
ZONE 0 — UNTRUSTED        Public internet. Any IP. No assumed identity.
ZONE 1 — API KEY HOLDERS  Valid Bearer token. Rate limited. Can submit proposals.
ZONE 2 — ADMIN KEY        COLONY_ADMIN_KEY. Operators. Federation calls.
ZONE 3 — BIOMETRIC        Physical presence. 90s token. Single-use. Gate 0.
ZONE 4 — FEDERATION PEERS Know COLONY_ADMIN_KEY. Cannot modify local chain.
ZONE 5 — RUST KERNEL      In-process. Highest trust. Memory-safe by construction.
```

---

## Threat Catalog

### T1 — Biometric Token Replay
**Category:** Authentication bypass
**Attack:** Steal a valid 90-second token and reuse it before expiry.
**Likelihood:** Medium (requires network interception)
**Impact:** High (bypasses Gate 0, actor impersonation)
**Mitigations:**
- 90-second TTL enforced in Rust kernel (GATE0_EXPIRED)
- Single-use flag in SQLite — token marked used on first verification
- HMAC-SHA256 signature — cannot be forged without COLONY_BAS_SECRET
**Residual risk:** 90-second window if token intercepted in transit.
**Recommended fix:** Reduce TTL to 30s for high-value transactions. Add TLS everywhere.

---

### T2 — Biometric Token Forgery
**Category:** Cryptographic attack
**Attack:** Forge a valid token without knowing COLONY_BAS_SECRET.
**Likelihood:** Very Low (requires breaking HMAC-SHA256)
**Impact:** Critical (complete Gate 0 bypass)
**Mitigations:**
- HMAC-SHA256 with constant-time comparison in Rust (no timing leaks)
- 256-bit secret key (COLONY_BAS_SECRET)
**Residual risk:** None if BAS_SECRET is strong and stable.
**Critical:** If COLONY_BAS_SECRET is not set, ephemeral key used — all tokens invalid on restart.

---

### T3 — Gate 3 Extraction Signature Evasion
**Category:** Content injection
**Attack:** Craft agent output containing extraction intent but evading 27 regex patterns.
**Likelihood:** Medium (determined attacker with pattern knowledge)
**Impact:** High (extraction attempt passes Gate 3)
**Mitigations:**
- 27 case-insensitive patterns with hyphen/underscore/space variants
- Patterns compiled once at load (OnceLock — no recompilation attack)
- Full JSON serialization of agent outputs before scan
**Residual risk:** Novel extraction patterns not yet in the list.
**Recommended fix:** Periodic pattern review. Semantic scanning layer (embedding-based).

---

### T4 — LQ Score Type Injection
**Category:** Type confusion
**Attack:** Submit a string LQ score ("0.99") or complex number to bypass Gate 2.
**Likelihood:** Low (requires API access)
**Impact:** Medium (Gate 2 bypass)
**Mitigations:**
- Python coerces non-numeric types to -1.0 before Rust call
- Rust Gate 2 rejects NaN, Inf, values outside [0.0, 1.0]
**Residual risk:** None — tested in test suite (test_colony_chaos.py).

---

### T5 — Federation Node Impersonation
**Category:** Identity spoofing
**Attack:** Rogue node claims to be node-001-bethel and injects false lineage records.
**Likelihood:** Medium (requires knowing COLONY_ADMIN_KEY)
**Impact:** High (false governance proposals, lineage pollution)
**Mitigations:**
- COLONY_ADMIN_KEY Bearer auth on all federation calls
- Lineage chain integrity check — forged records break hash chain
**Residual risk:** HIGH — any node knowing the admin key can impersonate any node_id.
**Recommended fix:** Ed25519 node keypair. node_id = public key fingerprint. Sign all federation messages.

---

### T6 — Lineage Chain Tampering
**Category:** Data integrity
**Attack:** Modify a historical lineage record in SQLite.
**Likelihood:** Low (requires direct DB access)
**Impact:** Critical (destroys audit trail integrity)
**Mitigations:**
- SHA-256 chain — any modification breaks all subsequent hashes
- WAL mode — concurrent reads don't block writes
- Append-only design — no UPDATE or DELETE on lineage table
**Residual risk:** SQLite file could be replaced entirely by someone with filesystem access.
**Recommended fix:** Periodic chain root publication to external immutable log. Merkle tree audit bundles (PFP INV-007).

---

### T7 — SaaS Cloaking
**Category:** License violation
**Attack:** Fork the code, remove covenant, run as closed hosted service.
**Likelihood:** Medium (technically straightforward)
**Impact:** Medium (covenant flow lost, mission violated)
**Mitigations:**
- AGPL v3 — must publish source modifications for hosted services
- 23 constitutional tests — CI rejects covenant removal
**Residual risk:** Legal enforcement required. Forker can disable CI.
**Recommended fix:** Proof of Covenant in federation handshake (PFP INV-006).

---

### T8 — Architect's Covenant Removal
**Category:** Covenant violation
**Attack:** Fork the code, change 3% split to 0%, redeploy.
**Likelihood:** Low (AGPL + tests create friction)
**Impact:** High (Architect receives nothing from derivative)
**Mitigations:**
- 23 constitutional tests guard the 3% split
- AGPL v3 requires publishing the modification
- Covenant fingerprint detectable in federation handshake
**Residual risk:** Forker can disable tests and CI.
**Recommended fix:** Proof of Covenant cryptographic verification before federation admission.

---

### T9 — Ephemeral Secret Key Attack
**Category:** Availability / token invalidation
**Attack:** Restart server repeatedly to invalidate all biometric tokens.
**Likelihood:** Low (requires server access)
**Impact:** Medium (all enrolled members lose access temporarily)
**Mitigations:**
- Warning logged at startup if COLONY_BAS_SECRET not set
- Documentation requires stable key in production
**Residual risk:** HIGH if COLONY_BAS_SECRET not set in production.
**Recommended fix:** Fail startup if COLONY_BAS_SECRET not set and COLONY_DEV_MODE=false.

---

### T10 — Rate Limit Bypass
**Category:** Denial of service
**Attack:** Use many different IPs to bypass per-key rate limiting.
**Likelihood:** Medium (botnets are common)
**Impact:** Low-Medium (server load, cost increase)
**Mitigations:**
- Per-key rate limiting when Bearer token present
- slowapi sliding window
**Residual risk:** Unauthenticated requests fall back to per-IP limiting.
**Recommended fix:** Global rate limit + IP reputation scoring.

---

### T11 — Crisis Escalation Bypass (SESSION_FLOW_SPEC)
**Category:** Safety bypass
**Attack:** Craft input that suppresses CrisisLevel detection, preventing 988 routing.
**Likelihood:** Low (requires understanding of crisis detection logic)
**Impact:** Critical (person in crisis does not receive help)
**Mitigations:**
- CrisisLevel evaluated by ANALYTICA before any other agent
- Crisis short-circuit bypasses all other gates
**Residual risk:** CrisisLevel detection is keyword-based — semantic evasion possible.
**Recommended fix:** Embedding-based crisis detection. Multiple detection layers.

---

### T12 — Session Replay (PFP INV-016)
**Category:** Replay attack
**Attack:** Replay a previously valid session to re-execute an approved transaction.
**Likelihood:** Low (requires session capture)
**Impact:** High (duplicate transactions, double-spend)
**Mitigations:**
- Single-use biometric tokens (90s TTL)
- Lineage chain records every transaction
**Residual risk:** No session anchor hash or Anchor Registry yet (PFP INV-013 gap).
**Recommended fix:** Implement session_id + anchor_hash at genesis (Tier 1 priority).

---

## Risk Matrix

| Threat | Likelihood | Impact | Priority |
|--------|-----------|--------|----------|
| T5 — Federation impersonation | Medium | High | CRITICAL |
| T9 — Ephemeral secret key | Low | Medium | HIGH |
| T12 — Session replay | Low | High | HIGH |
| T1 — Token replay | Medium | High | HIGH |
| T6 — Chain tampering | Low | Critical | HIGH |
| T3 — Gate 3 evasion | Medium | High | MEDIUM |
| T7 — SaaS cloaking | Medium | Medium | MEDIUM |
| T8 — Covenant removal | Low | High | MEDIUM |
| T11 — Crisis bypass | Low | Critical | MEDIUM |
| T2 — Token forgery | Very Low | Critical | LOW |
| T4 — LQ type injection | Low | Medium | LOW |
| T10 — Rate limit bypass | Medium | Low | LOW |

---

## Mitigations Implemented

| Mitigation | Status | File |
|-----------|--------|------|
| Constant-time HMAC | ✅ | aethel-kernel/src/lib.rs |
| Single-use tokens | ✅ | biometric.py |
| 90s TTL | ✅ | aethel-kernel/src/lib.rs |
| 27 extraction patterns | ✅ | aethel-kernel/src/lib.rs |
| LQ type coercion | ✅ | aethel_interface.py |
| SHA-256 chain | ✅ | db.py |
| Rate limiting | ✅ | rate_limit.py |
| AGPL v3 | ✅ | LICENSE |
| Constitutional tests | ✅ | tests/test_covenant.py |

## Mitigations Pending

| Mitigation | Priority | Target |
|-----------|----------|--------|
| Ed25519 node keypair | CRITICAL | v0.8.0 |
| Session anchor hash | HIGH | v0.7.3 |
| Startup secret enforcement | HIGH | v0.7.3 |
| Proof of Covenant handshake | HIGH | v0.8.0 |
| mTLS between nodes | MEDIUM | v0.9.0 |
| Semantic crisis detection | MEDIUM | v0.9.0 |
| Merkle audit bundles | MEDIUM | v1.0.0 |

---

*Node 001 — Bethel Acres — OpenClaw Colony v0.7.2*
*Cross-reference: GOVERNANCE.md, PFP-SPEC-2026-001.md, SESSION_FLOW_SPEC.md*
