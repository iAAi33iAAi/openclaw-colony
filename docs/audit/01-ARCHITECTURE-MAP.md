# OpenClaw Colony — Architecture Map
## Full-Stack Technical Audit — Deliverable 1 of 8

---

## System Overview

OpenClaw Colony is a sovereign governance and transaction safety system.
It is composed of six major subsystems operating in a defined hierarchy.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        OPENCLAW COLONY NODE                             │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  LAYER 6: OPERATOR INTERFACE                                    │   │
│  │  install.sh → docker-compose → Caddyfile → public HTTPS URL    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                │                                        │
│  ┌─────────────────────────────▼───────────────────────────────────┐   │
│  │  LAYER 5: FRONTEND (TypeScript/React)                           │   │
│  │  App.tsx → SevenAgentInterface.tsx → LoveQualityChecker.tsx     │   │
│  │  Vite build → Nginx → port 3000                                 │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                │ HTTP                                   │
│  ┌─────────────────────────────▼───────────────────────────────────┐   │
│  │  LAYER 4: API GATEWAY (FastAPI)                                 │   │
│  │  colony_coordinator_v2.py                                       │   │
│  │  ├── POST /process          (main transaction endpoint)         │   │
│  │  ├── POST /webhook/stripe   (MANNA payment events)             │   │
│  │  ├── GET  /health           (node health)                       │   │
│  │  ├── /admin/*               (key management, payments)         │   │
│  │  ├── /federation/*          (peer discovery, proposals)        │   │
│  │  └── /biometric/*           (enrollment, attestation)          │   │
│  │                                                                 │   │
│  │  Auth:       Bearer token (API keys in SQLite)                  │   │
│  │  Rate limit: slowapi per-key sliding window                     │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                │                                        │
│  ┌─────────────────────────────▼───────────────────────────────────┐   │
│  │  LAYER 3: COLONY PIPELINE (7 Agents + LQ Engine)               │   │
│  │                                                                 │   │
│  │  ColonyTask → [7 agents in parallel] → LoveQualityEngine       │   │
│  │                                                                 │   │
│  │  Agents (BaseAgent ABC):                                        │   │
│  │  StrategicAgent   TechnicalAgent   ResourcesAgent              │   │
│  │  CommsAgent       AnalysisAgent    QualityAgent                │   │
│  │  InnovationAgent                                               │   │
│  │                                                                 │   │
│  │  LQ Engine: 6 dimensions, weights sum to 1.0                   │   │
│  │  flourishing(0.25) harm_reduction(0.20) equity(0.20)           │   │
│  │  regenerative(0.15) cooperation(0.12) beauty(0.08)             │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                │ lq_score, agent_outputs                │
│  ┌─────────────────────────────▼───────────────────────────────────┐   │
│  │  LAYER 2: AETHEL INTERFACE (Python Bridge)                      │   │
│  │  aethel_interface.py                                            │   │
│  │                                                                 │   │
│  │  Gate 0: biometric.py (Python/SQLite — 10 checks)              │   │
│  │  Gates 1-3: aethel_kernel (Rust PyO3)                          │   │
│  │                                                                 │   │
│  │  Type coercion → bypass token mint → PyO3 call → result map    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                │ FFI                                    │
│  ┌─────────────────────────────▼───────────────────────────────────┐   │
│  │  LAYER 1: RUST SAFETY KERNEL (PyO3 native)                     │   │
│  │  aethel-kernel/src/lib.rs                                       │   │
│  │                                                                 │   │
│  │  Gate 0: HMAC-SHA256 verify + TTL + future-token check         │   │
│  │  Gate 1: human_consent bool                                     │   │
│  │  Gate 2: lq_score ∈ [0.0, 1.0] ∧ ≥ 0.85                      │   │
│  │  Gate 3: RegexSet(27 patterns) scan                             │   │
│  │  Chain:  SHA-256(prev||task||actor||outcome||ts)                │   │
│  │                                                                 │   │
│  │  Returns: GateResponse { approved, failed_gate, reason,        │   │
│  │                          new_lineage_hash, kernel_timestamp }   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                │                                        │
│  ┌─────────────────────────────▼───────────────────────────────────┐   │
│  │  LAYER 0: PERSISTENCE (SQLite WAL)                              │   │
│  │                                                                 │   │
│  │  lineage              — SHA-256 chain (append-only)             │   │
│  │  api_keys             — Bearer token registry                   │   │
│  │  payments             — Stripe MANNA records                    │   │
│  │  colony_members       — biometric enrollment                    │   │
│  │  biometric_attestations — 90s tokens                            │   │
│  │  accountability_log   — court-admissible ledger                 │   │
│  │  federated_nodes      — peer registry                           │   │
│  │  cross_node_proposals — governance votes                        │   │
│  │  federation_votes     — per-node vote records                   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  CROSS-CUTTING: FEDERATION LAYER                                │   │
│  │  federation.py + federation_routes.py + state_machine.py       │   │
│  │                                                                 │   │
│  │  NodeState:     STANDALONE→ANNOUNCING→SYNCING→LIVE↔ISOLATED    │   │
│  │  ProposalState: PENDING→APPROVED|BLOCKED|EXPIRED               │   │
│  │  TxState:       RECEIVED→G0→G1→G2→G3→APPROVED|BLOCKED→CHAINED │   │
│  │                                                                 │   │
│  │  Gossip:   POST /federation/lineage-tip (every 60s)            │   │
│  │  Quorum:   0.51 of active peers (configurable)                 │   │
│  │  Auth:     Bearer COLONY_ADMIN_KEY on all federation calls      │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
         │  HTTP Bearer auth
         ▼
┌──────────────────┐     ┌──────────────────┐
│  NODE 002        │────▶│  NODE 003        │
│  peer colony     │     │  peer colony     │
└──────────────────┘     └──────────────────┘
```

---

## Subsystem Responsibilities

| Subsystem | File(s) | Responsibility |
|-----------|---------|----------------|
| API Gateway | `colony_coordinator_v2.py` | Request routing, auth, rate limiting, orchestration |
| 7-Agent Pipeline | `colony-agents/*.py` | Parallel domain evaluation of proposals |
| LQ Engine | `love_quality_engine.py` | 6-dimension ethical scoring |
| Aethel Interface | `aethel_interface.py` | Python↔Rust bridge, Gate 0, type coercion |
| Rust Kernel | `aethel-kernel/src/lib.rs` | Gates 1-3, lineage chaining, HMAC |
| Biometric Layer | `biometric.py`, `biometric_routes.py` | Enrollment, attestation, accountability |
| Federation | `federation.py`, `federation_routes.py` | Peer discovery, gossip, proposals |
| State Machine | `state_machine.py` | Node/proposal/transaction lifecycle |
| Genesis | `dev_commit_init.py` | Startup sequence, genesis block |
| Payments | `stripe_bridge.py` | MANNA 84/15/1 split |
| Persistence | `db.py` | SQLite WAL, lineage chain |
| Auth | `auth.py` | Bearer token validation |
| Rate Limiting | `rate_limit.py` | Per-key sliding window |
| Frontend | `frontend/src/*.tsx` | React dashboard |
| Infra | `docker-compose.yml`, `Dockerfile.*`, `Caddyfile`, `install.sh` | Deployment |

---

## Data Flow — Happy Path

```
1. Client sends POST /process with Bearer token + ColonyTask
2. auth.py validates Bearer token against api_keys table
3. rate_limit.py checks per-key sliding window
4. 7 agents evaluate prompt in parallel → agent_outputs dict
5. LoveQualityEngine scores agent_outputs → LQScore (composite float)
6. AethelInterface.validate() called:
   a. Gate 0: biometric.verify_attestation_token() [Python/SQLite]
   b. Gates 1-3: aethel_kernel.verify_safety_kernel() [Rust PyO3]
7. If APPROVED:
   a. LineageRecord written to SQLite
   b. stripe_bridge.process_manna_payment() called (84/15/1 split)
   c. federation.broadcast_lineage_tip() called (async)
8. ColonyResult returned to client
```

---

## Critical Boundaries

| Boundary | Type | Risk |
|----------|------|------|
| Python → Rust (PyO3 FFI) | Type coercion | Incorrect types silently coerced |
| Gate 0 (Python) → Gates 1-3 (Rust) | Bypass token mint | Token must be valid HMAC |
| SQLite WAL | Concurrent writes | Single writer, multiple readers |
| Federation HTTP | Bearer auth | Shared secret across all nodes |
| Stripe webhook | Signature verify | STRIPE_WEBHOOK_SECRET required |
