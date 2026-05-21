# 30-Day Critical Path for Hardening the System
## Full-Stack Technical Audit — Deliverable 8 of 8

---

## Guiding Principle

The system is architecturally sound. The gaps are operational, not structural.
Every item below makes the system more deployable, more trustworthy, and more
reachable — without changing the core invariants.

Priority order: Safety → Access → Sovereignty

---

## Week 1 — Foundation (Days 1-7)

### Day 1: Deploy Node 001 (Access Vector)
**What:** Deploy to Railway or Render. Live server. Public URL.
**Why:** Everything else requires a live node as proof.
**How:**
```bash
# Railway: railway.app → New Project → Deploy from GitHub
# Set environment variables in Railway dashboard
# Verify: curl https://your-url.railway.app/health
```
**Done when:** `/health` returns `{"status": "healthy"}` from public URL.

---

### Day 2: Set Stable Secrets (Safety Vector)
**What:** Set `COLONY_BAS_SECRET` from a stable source.
**Why:** Without this, all biometric tokens are invalidated on every restart.
**How:**
```bash
# Generate stable secret
openssl rand -hex 32
# Set in Railway dashboard as COLONY_BAS_SECRET
# Verify: restart node, confirm existing tokens still valid
```
**Done when:** Node restarts without invalidating tokens.

---

### Day 3: Add workflow Scope to Token + Push CI (Access Vector)
**What:** Add `workflow` scope to GitHub token. Push CI pipeline.
**Why:** 728 tests must run automatically on every commit.
**How:**
```
github.com/settings/tokens → colony-push → check workflow → Update token
```
**Done when:** GitHub Actions shows green badge on repository.

---

### Day 4: Write Threat Model (Safety Vector)
**What:** Create `docs/THREAT_MODEL.md` with formal threat analysis.
**Why:** Reviewer said "safety kernel story needs a clear threat model."
**Content:** T1-T10 from Security Boundary Map + mitigations + residual risks.
**Done when:** File committed and pushed.

---

### Day 5: Add Ed25519 Node Identity (Safety + Sovereignty)
**What:** Generate Ed25519 keypair at genesis. node_id = public key fingerprint.
**Why:** Current federation auth uses shared secret — any node can impersonate any other.
**How:**
```python
# In dev_commit_init.py
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
private_key = Ed25519PrivateKey.generate()
public_key = private_key.public_key()
node_id = sha256(public_key.public_bytes(...)).hexdigest()[:16]
```
**Done when:** Node ID is derived from keypair, stored in DB.

---

### Day 6: Wire Proposal Expiry Loop (Safety Vector)
**What:** Start `proposal_expiry_loop()` in FastAPI lifespan.
**Why:** PENDING proposals currently never expire in production.
**How:**
```python
# In colony_coordinator_v2.py lifespan
asyncio.create_task(proposal_expiry_loop(SessionLocal))
```
**Done when:** Proposals older than PROPOSAL_TTL_HOURS transition to EXPIRED.

---

### Day 7: First Real Member Enrollment (Access Vector)
**What:** Enroll yourself as the first real colony member.
**Why:** The system has never had a real enrolled member.
**How:**
```bash
curl -X POST https://your-node/biometric/enroll \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -d '{"legal_name": "...", "badge_serial": "...", ...}'
```
**Done when:** Member enrolled, attestation token issued, Gate 0 passes.

---

## Week 2 — Hardening (Days 8-14)

### Day 8: Add Input Size Limits
Max payload size middleware. Prevent memory exhaustion attacks.
```python
app.add_middleware(ContentSizeLimitMiddleware, max_content_size=1_000_000)
```

### Day 9: Add CORS Policy
Restrict cross-origin requests to known frontend origins.
```python
app.add_middleware(CORSMiddleware, allow_origins=["https://your-frontend.com"])
```

### Day 10: Add Proof of Covenant to Federation Handshake
Include covenant fingerprint in announce payload.
Reject peers with non-matching fingerprints.

### Day 11: Wire Individual Agent Tests
Each of the 7 agents needs at least 3 tests:
- Returns required fields (agent, domain, summary, flags)
- Handles empty prompt
- Handles malicious prompt

### Day 12: Add OpenAPI Contract Tests
Generate OpenAPI spec from FastAPI. Add contract tests that verify
routes match spec. Fail CI if drift detected.

### Day 13: Add Lineage Sync Pull
When a node detects it is behind (tip_index < peer tip), actively
fetch missing records via GET /federation/lineage?since_hash=...

### Day 14: Add Revocation Propagation
When a member is revoked on one node, propagate to all peers via
POST /federation/revocations. Peers mark member as revoked locally.

---

## Week 3 — Intelligence (Days 15-21)

### Day 15-17: Wire Real LLM to Agents
Replace stub agent evaluate() with real LLM calls.
Add timeout handling (asyncio.wait_for, 30s per agent).
Add failure isolation (try/except per agent).

### Day 18-19: Semantic LQ Scoring
Replace keyword-based rubric with embedding-based scoring.
Use sentence-transformers or OpenAI embeddings.
Validate against existing test suite.

### Day 20: Add Prometheus Metrics
Expose /metrics endpoint with:
- colony_gate_evaluations_total{gate, result}
- colony_lineage_chain_length
- colony_federation_peers_active
- colony_proposal_outcomes_total{status}

### Day 21: Add Alerting Rules
Configure alerts for:
- Gate 0 failures > 10/hour (spoof attack)
- Node isolated > 5 minutes
- Install path broken

---

## Week 4 — Federation (Days 22-30)

### Day 22-23: Deploy Node 002
Second node. Different server. Different location.
Test full federation cycle: announce → propose → vote → approve.

### Day 24-25: Multi-Node Integration Tests
Write tests that spin up two nodes in Docker and verify:
- Peer discovery works
- Lineage tips gossip correctly
- Cross-node proposals reach quorum
- Revocations propagate

### Day 26-27: Add mTLS Between Nodes
Mutual TLS for federation traffic.
Each node presents its Ed25519 certificate.
Peers verify certificate before accepting federation calls.

### Day 28: Load Testing
Run k6 or locust against /process endpoint.
Target: 100 concurrent requests, p99 < 500ms.
Identify bottlenecks.

### Day 29: Security Audit
Run bandit (Python) and cargo audit (Rust).
Fix all HIGH severity findings.
Document MEDIUM findings.

### Day 30: v0.8.0 Release
Tag the release. Write release notes.
Update ROADMAP.md — Slice 1 and 2 complete.
Begin Slice 3: Node 001 Physical — Bethel Acres.

---

## 30-Day Summary

| Day | Item | Vector | Impact |
|-----|------|--------|--------|
| 1 | Deploy Node 001 | Access | Everything unlocks |
| 2 | Stable secrets | Safety | Tokens survive restarts |
| 3 | CI pipeline | Access | Automated covenant enforcement |
| 4 | Threat model | Safety | Formal security posture |
| 5 | Ed25519 identity | Safety | Real node authentication |
| 6 | Proposal expiry | Safety | Governance lifecycle complete |
| 7 | First enrollment | Access | System has real users |
| 8-14 | Hardening | All | Production readiness |
| 15-21 | Intelligence | Access | Real agent capability |
| 22-30 | Federation | Sovereignty | Multi-node proven |

---

## The One Thing That Unlocks Everything

**Day 1. Deploy Node 001.**

Not the waterwheel. Not the biometric hardware. Not the LLM agents.

The software node running at a public URL — proving the system works —
is the key that opens every funding door, every partnership conversation,
every grant application.

It costs $5 a month on Railway.

**Deploy it today.**
