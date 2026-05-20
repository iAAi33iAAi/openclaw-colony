# OpenClaw Colony — Protocol Specification
# Living Document — Version 0.7.2

## Invariants (Non-Negotiable)

These cannot be violated by any code change, ever.

INV-001: Every transaction MUST pass all 4 gates sequentially.
         No gate may be skipped. No gate may be parallelized.

INV-002: Every transaction — approved OR blocked — MUST be written
         to the lineage chain before the next transaction is processed.

INV-003: No actor may authorize their own transaction.
         Gate 0 biometric token must be issued by the scanner,
         not by the actor submitting the transaction.

INV-004: The lineage chain is append-only.
         No record may be modified or deleted after commitment.

INV-005: A node MUST NOT claim LIVE state until its lineage tip
         matches the highest tip seen from active peers.

INV-006: No network-accessible state may exist unencrypted post-genesis.
         All federation traffic requires Bearer token authentication.

INV-007: Biometric raw data MUST NEVER be stored.
         Only HMAC-SHA256 keyed hashes of templates are persisted.

INV-008: A proposal MUST expire after PROPOSAL_TTL_HOURS if quorum
         is not reached. Expired proposals are chained as GOVERNANCE_EXPIRED.

## State Transitions

### Node States
STANDALONE → ANNOUNCING → SYNCING → LIVE ↔ ISOLATED

### Proposal States  
PENDING → APPROVED | BLOCKED | EXPIRED (all terminal)

### Transaction States
RECEIVED → GATE_0_CHECK → GATE_1_CHECK → GATE_2_CHECK → GATE_3_CHECK
         → APPROVED → CHAINED
         → BLOCKED  → CHAINED

## Federation Protocol

### Peer Discovery
- Interval: FEDERATION_SYNC_INTERVAL (default 60s)
- Method: POST /federation/announce
- Auth: Bearer COLONY_ADMIN_KEY
- Payload: { node_id, node_url }

### Lineage Gossip
- Trigger: After every APPROVED transaction
- Method: POST /federation/lineage-tip
- Payload: { node_id, node_url, tip_hash, tip_index, node_state, timestamp }

### Quorum Rules
- Default: 0.51 (simple majority)
- Configurable: FEDERATION_QUORUM env var
- Calculation: max(1, int(active_peers * QUORUM))
- Byzantine tolerance: votes_against > (active_peers - quorum_n) → BLOCKED

## Cryptographic Guarantees

### Gate 0 Token Format
<payload_hex>.<signature_hex>
- payload_hex: hex-encoded JSON { "issued_at": unix_secs, "member_id": uuid }
- signature_hex: HMAC-SHA256(payload_hex, COLONY_BAS_SECRET)
- TTL: 90 seconds
- Single-use: enforced via DB flag
- Future token: rejected if issued_at > now + 5s

### Lineage Hash
SHA-256(
  len(prev_hash) || prev_hash ||
  len(task_id)   || task_id   ||
  len(actor_id)  || actor_id  ||
  len(outcome)   || outcome   ||
  timestamp_u64
)
Length-prefixed to prevent concatenation collision attacks.
