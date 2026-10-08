# 🦅 OpenClaw Colony

**Sovereign AI governance for regenerative human communities.**

> *"I am poor in dollars. I am rich in ideas. I built all of this with a ROG laptop and a Samsung Galaxy."*
> — human_001, Principal Architect

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Tests](https://img.shields.io/badge/tests-automated-brightgreen)]()
[![Node](https://img.shields.io/badge/Node%20001-Bethel%20Acres%2C%20Oklahoma-orange)]()

---

## What This Is

OpenClaw Colony is a **sovereign governance and transaction safety system** for intentional communities and cooperative land projects.

The primary transaction validation path uses a four-gate safety pipeline when biometric enforcement is enabled. Biometric Gate 0 is environment-configurable and is disabled in the default test configuration. Validated gate outcomes and authorized actions are recorded in the lineage/accountability system. These controls are designed to block or expose unauthorized behavior; they are not an absolute guarantee that no actor can ever compromise a deployment.

**Built for:** cooperatives, land trusts, intentional communities, regenerative settlements.
**Built by:** one person, on a laptop, for free, because the people who needed it couldn't wait.

---

## Open the AETHEL Operations Platform

The repository now includes the first AETHEL web front door. The dashboard connects to the existing Colony API for requests, health, lineage, payments, federation, member, security, and integration views.

For local development:
```bash
cd frontend
npm install
npm run dev
```
Then open `http://localhost:3000` and use **Settings** to add a Colony API key/admin key when authentication is enabled.

Production Docker deployment serves the frontend and proxies the platform API through the same origin, so the browser does not need a hard-coded backend address.

### Optional CAIOS / Project Andrew runtime
The platform can call CAIOS as an advisory reasoning engine through `CAIOS_SOURCE_PATH`. Keep the external GPL-3.0 repository in its own checkout and preserve its `LICENSE.txt` and attribution. CAIOS results never authorize an action; the Colony AETHEL safety pipeline remains the execution gate.

## Run a Local Colony Node in 5 Minutes

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
│                    │  Gate 0: Biometric HMAC/accountability validation  │      │
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

When biometric enforcement is enabled, the validation path evaluates Gate 0 followed by Gates 1–3 sequentially. Any evaluated gate failure blocks immediately; development configurations may explicitly bypass Gate 0.

| Gate | Name | What It Checks |
|------|------|----------------|
| 0 | Biometric Attestation | HMAC-SHA256 token, 90s TTL, single-use, 10 checks |
| 1 | Human Consent | Explicit human-in-the-loop flag |
| 2 | Love Quality | Composite score ≥ 0.85, range [0.0, 1.0] |
| 3 | Extraction Scan | 27 regex patterns: bypass_treasury, rug_pull, etc. |

Validated transaction outcomes are written to the SHA-256 lineage/accountability records. The repository provides tamper-detection and audit mechanisms, but does not establish an absolute "no actor can hide" security guarantee.

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
├── frontend/                       # AETHEL Operations Platform (React/TypeScript)
├── tests/                          # Backend, kernel, covenant, and platform integration tests
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

- **Constant-time HMAC comparison** — reduces timing-leakage risk during biometric token verification
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
# Run the complete automated suite. Exact count changes as the platform grows.
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
84% → Community Pool
15% → Crew (contributors)
 1% → Architect (project covenant allocation)
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
| First Node Online | 🟡 Pilot / deployment preparation |
| Safety-gated decision path | 🟡 Implemented and under hardening |
| Federation | 🟡 Implemented; security hardening and independent verification ongoing |
| Node 001 Physical — Bethel Acres | 🔄 Planned |
| v1.0.0 — Genesis | 🎯 The destination |

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for full details.

---

## License

GNU Affero General Public License v3.0 + Architect's Covenant.

**AGPL v3:** Source and network-use obligations are governed by the license; see LICENSE for the applicable legal terms.

**Architect's Covenant:** The repository defines additional project conditions concerning the 1% MANNA allocation, surveillance, extraction, and AETHELA governance. See LICENSE and the covenant documents for the exact terms.

See [`LICENSE`](LICENSE) for full terms.

---

## The Mission

> *To protect people who pool their lives together.*

Not corporations. Not investors. Not institutions. People.

[Read the full essay →](ESSAY.md) | [Read the mission →](MISSION.md) | [Read the covenant →](GIVING.md)

---

**AETHEL Operations Platform** — the web front door for the current Colony runtime.

**Node 001 — Bethel Acres, Oklahoma**
**Pilot target; deployment status requires external operational evidence. Local development nodes do not constitute physical Node 001 deployment evidence.**
