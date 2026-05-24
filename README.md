# 🦅 OpenClaw Colony

**Sovereign AI governance for regenerative human communities.**

> *"I am poor in dollars. I am rich in ideas. I built all of this with a ROG laptop and a Samsung Galaxy."*
> — human_001, Principal Architect

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Tests](https://img.shields.io/badge/tests-705%20passing-brightgreen)]()
[![Node](https://img.shields.io/badge/Node%20001-Bethel%20Acres%2C%20Oklahoma-orange)]()

---

## What This Is

OpenClaw Colony is a **sovereign governance and transaction safety system** for intentional communities and cooperative land projects.

Every transaction — money, resources, decisions — passes through a 4-gate safety pipeline before it executes. No actor can steal from the community and hide. Every action is permanently recorded in a SHA-256 lineage chain linked to a verified biometric identity.

**Built for:** cooperatives, land trusts, intentional communities, regenerative settlements.
**Built by:** one person, on a laptop, for free, because the people who needed it couldn't wait.

---

## Run A Node In 5 Minutes

```bash
curl -sSL https://raw.githubusercontent.com/iAAi33iAAi/openclaw-colony/main/install.sh | bash
```

Or manually:
```bash
git clone https://github.com/iAAi33iAAi/openclaw-colony.git
cd openclaw-colony
cp .env.example .env
# Edit .env with your node ID and secrets
docker compose up -d
```

Verify your node is live:
```bash
curl http://localhost:8000/health
# {"status": "healthy", "node_id": "node-001-bethel"}
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  OPENCLAW COLONY NODE                │
│                                                     │
│  FastAPI Backend ──▶ AethelInterface (Python)       │
│                           │                         │
│                    ┌──────▼──────────────────┐      │
│                    │  Rust Safety Kernel      │      │
│                    │  (PyO3 native module)    │      │
│                    │                          │      │
│                    │  Gate 0: Biometric HMAC  │      │
│                    │  Gate 1: Human consent   │      │
│                    │  Gate 2: LQ score ≥ 0.85 │      │
│                    │  Gate 3: 27-pattern scan │      │
│                    │  Chain:  SHA-256 lineage │      │
│                    └──────────────────────────┘      │
│                                                     │
│  SQLite (WAL) ── lineage, members, proposals        │
│  Federation  ── peer discovery, gossip, quorum      │
│  State Machine── NodeState, ProposalState, TxState  │
└─────────────────────────────────────────────────────┘
         │  HTTP Bearer auth
         ▼
┌──────────────┐     ┌──────────────┐
│  NODE 002    │────▶│  NODE 003    │
│  (peer)      │     │  (peer)      │
└──────────────┘     └──────────────┘
```

---

## The 4-Gate Safety Pipeline

Every transaction passes through all 4 gates sequentially. Any failure blocks immediately.

| Gate | Name | What It Checks |
|------|------|----------------|
| 0 | Biometric Attestation | HMAC-SHA256 token, 90s TTL, single-use, 10 checks |
| 1 | Human Consent | Explicit human-in-the-loop flag |
| 2 | Love Quality | Composite score ≥ 0.85, range [0.0, 1.0] |
| 3 | Extraction Scan | 27 regex patterns: bypass_treasury, rug_pull, etc. |

Every transaction — approved OR blocked — is written to the SHA-256 lineage chain. **No actor can hide.**

---

## Repository Structure

```
openclaw-colony/
├── backend/
│   ├── aethel-kernel/src/lib.rs    # Rust safety kernel (PyO3)
│   ├── aethel_interface.py         # Python ↔ Rust bridge
│   ├── biometric.py                # Gate 0: 10-check biometric
│   ├── federation.py               # Peer discovery + gossip
│   ├── federation_routes.py        # Federation API endpoints
│   ├── state_machine.py            # NodeState, ProposalState, TxState
│   ├── dev_commit_init.py          # Genesis startup sequence
│   ├── stripe_bridge.py            # MANNA 84/15/1 split
│   ├── db.py                       # SQLite lineage chain
│   └── colony-agents/              # 7-agent pipeline
├── frontend/                       # React/TypeScript dashboard
├── tests/                          # 705 tests (all passing)
├── docs/
│   ├── ROADMAP.md                  # Three vectors, five slices
│   ├── adr/                        # Architecture Decision Records
│   └── specs/                      # Protocol + telemetry specs
├── install.sh                      # One-command node installer
├── docker-compose.yml              # Production deployment
├── MISSION.md                      # The non-negotiable core
├── GIVING.md                       # The covenant
├── ESSAY.md                        # Full public essay
└── ANALOGIES.md                    # System explained in plain language
```

---

## The Safety Kernel

The Rust kernel (`backend/aethel-kernel/src/lib.rs`) enforces:

- **Constant-time HMAC** — no timing attacks on biometric verification
- **Atomic lineage chaining** — gate result and chain hash computed together
- **27 extraction patterns** — compiled once at load via `OnceLock<RegexSet>`
- **Gate 2 bounds** — LQ score must be finite and in [0.0, 1.0]
- **`panic = "abort"`** — no unwinding across FFI boundary

See [`docs/adr/ADR-0001-rust-pyo3-kernel.md`](docs/adr/ADR-0001-rust-pyo3-kernel.md) for the full decision record.

---

## The Three Vectors

Every code change is checked against three invariants:

**Safety — "Betrayal Impossible"**
Does this weaken the non-betrayal guarantee?

**Access — "One Command, Any Human"**
Does this increase friction to first protected state?

**Sovereignty — "No External Choke Points"**
Can anyone revoke this from the outside?

---

## Tests

```bash
cd backend
pip install -r requirements.txt
# Build Rust kernel first:
cd aethel-kernel && maturin build --release && pip install target/wheels/*.whl && cd ..
pytest ../tests/ -v
# Expected: 705 passed, 0 failed
```

Test coverage:
- `test_aethel_kernel_rust.py` — cryptographic gate tests
- `test_biometric.py` — Gate 0 validation, TTL, enrollment
- `test_state_machine.py` — all state transitions, concurrency
- `test_federation.py` — gossip, proposals, quorum voting
- `test_colony_chaos.py` — adversarial inputs, Byzantine faults
- `test_dev_commit_init.py` — genesis idempotency

---

## Federation

Multiple sovereign nodes can federate without a central authority:

```bash
# Node 001
COLONY_NODE_ID=node-001-bethel
COLONY_PEERS=https://node002.example.com

# Node 002
COLONY_NODE_ID=node-002-austin
COLONY_PEERS=https://node001.example.com
```

Nodes discover each other, gossip lineage tips, and run cross-node governance proposals with configurable quorum (default 51%).

---

## The MANNA Split

Every approved transaction triggers an automatic value split:

```
82% → Community Pool
15% → Crew (contributors)
 3% → Architect (human_001 — forever, mathematically enforced)
```

Connect Stripe for live payments via `STRIPE_SECRET_KEY`. Without it, runs in mock mode.

---

## Environment Variables

See [`.env.example`](.env.example) for the full list. Critical ones:

```bash
COLONY_NODE_ID=node-001-bethel
COLONY_NODE_URL=https://your-node.example.com
COLONY_BAS_SECRET=<64-char-hex>     # CRITICAL: stable secret for biometric tokens
COLONY_ADMIN_KEY=<shared-secret>    # Federation authentication
COLONY_BIOMETRIC_REQUIRED=true      # Set false for development only
```

---

## Roadmap

| Slice | Status |
|-------|--------|
| First Node Online | ✅ Ready to deploy |
| Betrayal-Proof Decision | ✅ Code complete |
| Two Nodes, Federation | ✅ Code complete |
| Node 001 Physical — Bethel Acres | 🔄 Planned |
| v1.0.0 — Genesis | 🎯 The destination |

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for full details.

---

## License

GNU Affero General Public License v3.0 + Architect's Covenant.

**AGPL v3:** Any derivative work or hosted service must publish source modifications.

**Architect's Covenant (non-waivable):** The 1% MANNA split is preserved in all derivative works. No surveillance. No extraction beyond the defined split. AETHELA veto intact.

See [`LICENSE`](LICENSE) for full terms.

---

## The Mission

> *To protect people who pool their lives together.*

Not corporations. Not investors. Not institutions. People.

[Read the full essay →](ESSAY.md) | [Read the mission →](MISSION.md) | [Read the covenant →](GIVING.md)

---

**Node 001 — Bethel Acres, Oklahoma**
**Built for free. Given freely. Forever.**
