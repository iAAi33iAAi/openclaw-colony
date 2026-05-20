# OpenClaw Colony — Living Roadmap

## The Three Vectors

Every decision, every feature, every line of code is checked against three invariants.
These are non-negotiable. They cannot be traded away for convenience, speed, or funding.

### Vector 1: Safety — "Betrayal Impossible"
Every change must answer: **Does this weaken the non-betrayal guarantee?**
- Biometric non-repudiation must hold
- Lineage chain must be append-only and tamper-evident
- Gate pipeline must be sequential and short-circuit on failure
- No actor can authorize their own transaction

### Vector 2: Access — "One Command, Any Human"
Every change must answer: **Does this increase or decrease friction to first protected state?**
- A non-technical community member must be able to deploy a node
- The installer must work on any Linux machine with Docker
- No Rust compiler required on the host
- No database administration required
- Time from zero to enrolled member: under 15 minutes

### Vector 3: Sovereignty — "No External Choke Points"
Every change must answer: **Can anyone revoke this from the outside?**
- No dependency on a central server
- No license that can be revoked
- No platform that can deplatform a node
- Federation must work without a registry
- Data must be portable and self-hosted

---

## Current State: v0.7.2

```
Commit:  23aa095
Tests:   705 passing, 0 failing
Status:  Pre-production — code complete, world not yet connected
```

---

## The Slices

### Slice 1: First Node Online
**Vector:** Access
**Status:** READY TO DEPLOY

Definition of Done:
- [ ] Node running at public URL
- [ ] COLONY_BAS_SECRET set from stable source
- [ ] Genesis block committed on live server
- [ ] /health endpoint responding
- [ ] /federation/status returning node state
- [ ] install.sh verified on clean machine

Required:
- GitHub token → push to iAAi33iAAi/openclaw-colony
- Railway/Render account → deploy backend
- Domain (optional) → Caddyfile handles HTTPS automatically

---

### Slice 2: Betrayal-Proof Decision
**Vector:** Safety
**Status:** CODE COMPLETE — needs live test

Definition of Done:
- [ ] First real member enrolled (biometric token issued)
- [ ] First real proposal submitted
- [ ] All 4 gates evaluated on real transaction
- [ ] Result written to lineage chain
- [ ] Accountability log entry created
- [ ] Transaction visible in /federation/status

Required:
- Enrolled member (can use dev mode biometric for first test)
- API call to /process with real payload

---

### Slice 3: Two Nodes, One Federation
**Vector:** Sovereignty
**Status:** CODE COMPLETE — needs second node

Definition of Done:
- [ ] Node 002 deployed (any machine, any location)
- [ ] Node 001 announces to Node 002
- [ ] Lineage tips gossiped between nodes
- [ ] Cross-node proposal submitted from Node 001
- [ ] Node 002 votes automatically via LQ engine
- [ ] Quorum reached, proposal resolved
- [ ] Both lineage chains updated

Required:
- Second server ($5/month on any VPS)
- COLONY_PEERS set on both nodes

---

### Slice 4: Node 001 Physical — Bethel Acres
**Vector:** Safety + Access + Sovereignty
**Status:** PLANNED

Definition of Done:
- [ ] Physical badge scanner connected
- [ ] Facial recognition camera connected
- [ ] Retinal scanner connected (or equivalent)
- [ ] First real biometric enrollment (not dev mode)
- [ ] First real transaction with physical biometric token
- [ ] QUIBIDT telemetry sensors embedded in earthbag walls
- [ ] Sensor data feeding into kernel environmental veto

---

### Slice 5: v1.0.0 — Genesis
**Vector:** All three
**Status:** THE DESTINATION

Definition of Done:
- [ ] Real human
- [ ] Real biometric
- [ ] Real MANNA moving through Stripe
- [ ] All 4 gates on real hardware
- [ ] Permanent lineage record
- [ ] Node 001 Bethel Acres is live
- [ ] The people who pool their lives together are protected

---

## The Feedback Loop

```
Field → Telemetry → Spec Delta → Code → CI → Deploy → Field
```

Every incident becomes:
1. An incident document in docs/incidents/
2. A spec delta in docs/adr/
3. A roadmap item in this file
4. A test in tests/

The roadmap is never finished. It listens to the field.

---

## Architecture Decision Records

All significant decisions are recorded in docs/adr/
Format: ADR-XXXX-title.md

Current ADRs:
- ADR-0001: Rust PyO3 kernel over Python fallback
- ADR-0002: SQLite over PostgreSQL for node-local chain
- ADR-0003: Lineage chaining in Rust (atomic with gate result)
- ADR-0004: State machine for node lifecycle
- ADR-0005: One-command installer over manual deployment

---

*This roadmap is a living document.*
*It changes when the field changes.*
*It holds when the vectors hold.*
*It serves the mission. Always.*

Node 001 — Bethel Acres — OpenClaw Colony
