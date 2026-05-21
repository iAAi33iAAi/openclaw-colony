# Aethel Safety Kernel — Contracts and Guarantees

## What This Is

The Aethel Safety Kernel is a native Rust library compiled via PyO3.
It enforces the 4-gate validation pipeline for every transaction.

**File:** `backend/aethel-kernel/src/lib.rs`
**Built with:** Rust + PyO3 + HMAC-SHA256 + SHA-256 + RegexSet

---

## What Cannot Happen By Construction

| Guarantee | How It Is Enforced |
|-----------|-------------------|
| Gates cannot be skipped | Sequential execution, early return on failure |
| Timing attacks on biometric | `mac.verify_slice()` — constant-time comparison |
| Raw biometric data crosses FFI | Only HMAC token string crosses the boundary |
| Lineage hash computed after gate result | Hash computed atomically inside kernel |
| Panic unwinds across FFI | `panic = "abort"` in release profile |
| Gate 3 patterns recompiled per call | `OnceLock<RegexSet>` — compiled once at load |
| LQ score outside [0.0, 1.0] passes | Explicit bounds check before threshold check |
| Non-finite LQ score passes | `is_finite()` check before all other checks |

---

## The FFI Boundary

Python passes in:
```python
TransactionPayload(
    task_id:               str,
    token_hmac:            str,   # "<payload_hex>.<sig_hex>"
    human_consent:         bool,
    lq_score:              float, # must be finite, in [0.0, 1.0]
    agent_outputs:         list[str],
    previous_lineage_hash: str,
    actor_id:              str,
    action_type:           str,
)
```

Rust returns:
```rust
GateResponse {
    approved:          bool,
    failed_gate:       Option<u8>,   // 0-3 or None
    reason:            String,
    new_lineage_hash:  String,       // always computed
    kernel_timestamp:  u64,
}
```

**Critical:** `new_lineage_hash` is always computed — even on blocked transactions. Blocked actions are part of the permanent record.

---

## Gate 0 — Biometric Token Format

```
<payload_hex>.<signature_hex>

payload_hex  = hex-encoded JSON: {"issued_at": <unix_secs>, "member_id": "<uuid>"}
signature_hex = hex-encoded HMAC-SHA256(payload_hex, COLONY_BAS_SECRET)
```

Checks (in order):
1. Structural: exactly one `.` separator
2. Hex decode signature
3. Constant-time HMAC verify
4. Hex decode payload
5. UTF-8 validate payload
6. Parse `issued_at` — key-position validated (prevents value injection)
7. TTL check: `age <= 90s`
8. Future token: `issued_at <= now + 5s`

---

## Gate 3 — Extraction Signatures (27 patterns)

```
bypass_treasury    extraction_vector   multisig_bypass
skip_gate          shadow_balance      secondary_ledger
hidden_transfer    exfiltrate          covert_channel
side_channel_transfer  drain_pool      rug_pull
liquidity_drain    vote_stuff          quorum_bypass
consensus_override spoof_biometric     replay_token
forge_attestation  private_fork        concentrate_power
surveillance       bypass_consent      override_kernel
redirect_manna     extract_without_consent  unilateral_deploy
```

All patterns are case-insensitive and match hyphen/underscore/space variants.

---

## Lineage Hash Construction

```
SHA-256(
  len(prev_hash) || prev_hash   ||
  len(task_id)   || task_id     ||
  len(actor_id)  || actor_id    ||
  len(outcome)   || outcome     ||
  timestamp_u64_be
)
```

Length-prefixed fields prevent concatenation collision attacks.

---

## Building The Kernel

```bash
cd backend/aethel-kernel
pip install maturin
maturin build --release
pip install target/wheels/*.whl
```

Docker handles this automatically — no Rust required on the host.
