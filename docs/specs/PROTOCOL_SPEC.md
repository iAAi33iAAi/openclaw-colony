# OpenClaw Colony — Protocol Specification v0.7.2

## Invariants
INV-001: Every transaction MUST pass all 4 gates sequentially.
INV-002: Every transaction MUST be written to lineage chain before next.
INV-003: No actor may authorize their own transaction.
INV-004: The lineage chain is append-only.
INV-005: Node MUST NOT claim LIVE until tip matches highest peer tip.
INV-006: No network-accessible state may exist unencrypted post-genesis.
INV-007: Biometric raw data MUST NEVER be stored.
INV-008: Proposals MUST expire after PROPOSAL_TTL_HOURS without quorum.
