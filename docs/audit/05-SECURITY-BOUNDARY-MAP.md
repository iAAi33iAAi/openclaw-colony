# Security Boundary Map
## Full-Stack Technical Audit — Deliverable 5 of 8

---

## Trust Zones

```
ZONE 0 — UNTRUSTED (public internet)
  Any HTTP client, any IP address
  No assumed identity

ZONE 1 — API KEY HOLDERS (authenticated clients)
  Valid Bearer token in api_keys table
  Rate limited per key
  Can submit proposals via POST /process

ZONE 2 — ADMIN KEY HOLDERS (operators)
  COLONY_ADMIN_KEY env var
  Can manage API keys, view payments
  Can call federation endpoints

ZONE 3 — BIOMETRIC MEMBERS (enrolled humans)
  Physical presence at scanner
  Biometric token issued (90s TTL, single-use)
  Can authorize Gate 0

ZONE 4 — FEDERATION PEERS (other nodes)
  Know COLONY_ADMIN_KEY (shared secret)
  Can announce, gossip, propose, vote
  Cannot modify local lineage chain

ZONE 5 — KERNEL (Rust, in-process)
  Highest trust — enforces all invariants
  No external calls
  Memory-safe by construction
```

---

## Authentication Boundaries

| Endpoint | Auth Required | Method |
|----------|--------------|--------|
| POST /process | Yes | Bearer API key |
| GET /health | No | Public |
| GET /docs | No | Public |
| POST /admin/* | Yes | Bearer COLONY_ADMIN_KEY |
| POST /federation/* | Yes | Bearer COLONY_ADMIN_KEY |
| POST /biometric/* | Yes | Bearer API key |
| POST /webhook/stripe | Yes | Stripe signature |

---

## Cryptographic Inventory

| Component | Algorithm | Key Source | Rotation |
|-----------|-----------|------------|---------|
| Biometric token signing | HMAC-SHA256 | COLONY_BAS_SECRET | Manual |
| Lineage chain | SHA-256 | Deterministic | N/A |
| API key storage | SHA-256 hash | Random at creation | Per key |
| Federation auth | Bearer (plaintext) | COLONY_ADMIN_KEY | Manual |
| Stripe webhook | HMAC-SHA256 | STRIPE_WEBHOOK_SECRET | Stripe |

---

## Threat Model

### T1 — Biometric Token Replay
**Attack:** Steal a valid token and reuse it.
**Mitigation:** 90s TTL + single-use flag in DB.
**Residual risk:** 90s window if token intercepted in transit.
**Recommended fix:** Reduce TTL to 30s for high-value transactions.

### T2 — Biometric Token Forgery
**Attack:** Forge a token without knowing COLONY_BAS_SECRET.
**Mitigation:** HMAC-SHA256 constant-time verification in Rust.
**Residual risk:** None if BAS_SECRET is strong and stable.
**Critical:** If COLONY_BAS_SECRET is not set, ephemeral key used — all tokens invalid on restart.

### T3 — Gate 3 Evasion
**Attack:** Craft agent output that contains extraction signature but evades regex.
**Mitigation:** 27 patterns with case-insensitive, hyphen/underscore/space variants.
**Residual risk:** Novel extraction patterns not in the list.
**Recommended fix:** Periodic pattern review + semantic scanning layer.

### T4 — LQ Score Manipulation
**Attack:** Submit a string LQ score ("0.99") to bypass Gate 2.
**Mitigation:** Python coerces non-numeric types to -1.0 before Rust call.
**Residual risk:** None — tested in test suite.

### T5 — Federation Impersonation
**Attack:** Rogue node claims to be node-001-bethel.
**Mitigation:** COLONY_ADMIN_KEY Bearer auth.
**Residual risk:** HIGH — any node knowing the admin key can impersonate any node_id.
**Recommended fix:** Ed25519 node keypair — node_id = public key fingerprint.

### T6 — Lineage Chain Tampering
**Attack:** Modify a historical lineage record.
**Mitigation:** SHA-256 chain — any modification breaks all subsequent hashes.
**Residual risk:** SQLite file could be replaced entirely.
**Recommended fix:** Periodic chain root publication to external immutable log.

### T7 — SaaS Cloaking
**Attack:** Fork the code, remove covenant, run as closed service.
**Mitigation:** AGPL v3 — must publish modifications.
**Residual risk:** Legal enforcement required.

### T8 — Covenant Removal
**Attack:** Fork the code, remove 1% MANNA split.
**Mitigation:** 23 constitutional tests fail → CI rejects.
**Residual risk:** Forker can disable CI checks.
**Recommended fix:** Proof of Covenant in federation handshake.

### T9 — Ephemeral Secret Key
**Attack:** Restart server to invalidate all existing tokens.
**Mitigation:** Warning logged. Stable key required in production.
**Residual risk:** HIGH if COLONY_BAS_SECRET not set.
**Recommended fix:** Require COLONY_BAS_SECRET in production startup check.

### T10 — Rate Limit Bypass
**Attack:** Use many different IPs to bypass per-key rate limiting.
**Mitigation:** Per-key limiting when Bearer token present.
**Residual risk:** Unauthenticated requests fall back to per-IP.

---

## Missing Security Boundaries (Gaps)

| Gap | Severity | Recommended Fix |
|-----|----------|----------------|
| No node keypair (Ed25519) | CRITICAL | Generate at genesis, store in DB |
| No message signing in federation | CRITICAL | Sign all federation messages |
| No COLONY_BAS_SECRET enforcement | HIGH | Fail startup if not set in production |
| No mTLS between nodes | HIGH | Add mutual TLS for federation |
| No audit log for admin actions | HIGH | Log all /admin/* calls |
| No token revocation endpoint | MEDIUM | POST /biometric/revoke |
| No rate limiting on federation | MEDIUM | Add per-peer rate limiting |
| No input size limits | MEDIUM | Add max payload size middleware |
| No SQL injection protection | LOW | SQLAlchemy ORM (already protected) |
| No CORS policy | LOW | Add CORS middleware |
