# Federation Protocol Specification
## Full-Stack Technical Audit — Deliverable 4 of 8

---

## Federation Model

- Each node is sovereign. No central authority.
- Nodes discover each other via configured COLONY_PEERS.
- Lineage tips are gossiped every FEDERATION_SYNC_INTERVAL seconds.
- Cross-node proposals require FEDERATION_QUORUM fraction of active peers.
- All federation traffic authenticated with COLONY_ADMIN_KEY Bearer token.

---

## Node Identity

| Field | Source | Format |
|-------|--------|--------|
| node_id | COLONY_NODE_ID env | String, e.g. "node-001-bethel" |
| node_url | COLONY_NODE_URL env | HTTPS URL |
| admin_key | COLONY_ADMIN_KEY env | Shared secret (Bearer token) |

**Current gap:** Node identity is not cryptographically bound.
Any node that knows COLONY_ADMIN_KEY can impersonate any node_id.
**Fix:** Add Ed25519 node keypair — node_id = public key fingerprint.

---

## Message Formats

### Announce (POST /federation/announce)
```json
{
  "node_id":  "node-001-bethel",
  "node_url": "https://node001.openclaw.net"
}
```
Response:
```json
{
  "status":       "registered",
  "node_id":      "node-001-bethel",
  "our_node_id":  "node-002-austin",
  "our_node_url": "https://node002.openclaw.net"
}
```

### Lineage Tip Gossip (POST /federation/lineage-tip)
```json
{
  "node_id":    "node-001-bethel",
  "node_url":   "https://node001.openclaw.net",
  "tip_hash":   "a3f5c2...",
  "tip_index":  147,
  "node_state": "live",
  "timestamp":  "2026-05-21T09:00:00Z"
}
```

### Cross-Node Proposal (POST /federation/proposals)
```json
{
  "proposal_id": "550e8400-e29b-41d4-a716-446655440000",
  "origin_node": "node-001-bethel",
  "prompt_hash": "sha256_of_description",
  "description": "Allocate 500 MANNA to solar installation",
  "created_at":  "2026-05-21T09:00:00Z"
}
```

### Vote (POST /federation/votes)
```json
{
  "proposal_id": "550e8400-...",
  "voter_node":  "node-002-austin",
  "vote":        "approve",
  "lq_score":    "0.9100"
}
```

### Heartbeat (POST /federation/heartbeat)
```json
{
  "node_id":   "node-001-bethel",
  "node_url":  "https://node001.openclaw.net",
  "old_state": "syncing",
  "new_state": "live",
  "reason":    "lineage head check passed",
  "timestamp": "2026-05-21T09:00:00Z"
}
```

---

## State Machine

### Node States
```
STANDALONE  → no peers configured
ANNOUNCING  → broadcasting to peers on startup
SYNCING     → pulling missing lineage records
LIVE        → fully operational (our_tip >= highest_peer_tip)
ISOLATED    → no peer contact > NODE_ISOLATION_TIMEOUT seconds
```

### SYNCING → LIVE Guard (Lineage Head Check)
```python
if our_tip < highest_peer_tip:
    # BLOCKED — still catching up
    return False
```
A node MUST NOT claim LIVE until its lineage tip matches the highest
tip seen from active peers. This prevents split-brain acceptance.

### Proposal States
```
PENDING  → collecting votes
APPROVED → votes_for >= quorum
BLOCKED  → votes_against > (peers - quorum)
EXPIRED  → created_at + PROPOSAL_TTL_HOURS < now
```

---

## Quorum Calculation

```python
quorum_n = max(1, int(active_peers * QUORUM))
# APPROVED if: votes_for >= quorum_n
# BLOCKED  if: votes_against > (active_peers - quorum_n)
```

Default QUORUM = 0.51 (simple majority).

---

## Proof of Covenant (Foundation)

Every node generates a covenant fingerprint:
```python
SHA-256(
  f"LQ_THRESHOLD={lq_threshold}"
  f"ARCHITECT_SPLIT={architect_bps}"
  f"COMMUNITY_SPLIT={community_bps}"
  f"CREW_SPLIT={crew_bps}"
  f"GENESIS_PREV={genesis_prev_hash}"
  f"GENESIS_TASK={genesis_task_id}"
  f"EXTRACTION_COUNT={pattern_count}"
)
```

**Future:** Exchange fingerprint during announce handshake.
Nodes with non-matching fingerprints are rejected from the lattice.

---

## Missing Protocol Definitions (Gaps)

| Gap | Priority | Recommended Fix |
|-----|----------|----------------|
| No cryptographic node identity | CRITICAL | Ed25519 keypair per node |
| No lineage sync pull | HIGH | Implement fetch_lineage_records() trigger |
| No revocation propagation | HIGH | POST /federation/revocations endpoint |
| No Proof of Covenant in handshake | HIGH | Add fingerprint to announce payload |
| No message signing | HIGH | Sign all federation messages with node key |
| No Byzantine fault tolerance | MEDIUM | Implement PBFT or Tendermint-lite |
| No peer reputation scoring | MEDIUM | Track peer reliability over time |
| No NAT traversal | MEDIUM | Add STUN/relay for non-public nodes |
| No lineage conflict resolution | MEDIUM | Define fork-choice rule |
| Proposal TTL not enforced in routes | LOW | Wire proposal_expiry_loop to startup |
