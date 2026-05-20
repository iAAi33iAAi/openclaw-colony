# ADR-0003: Lineage Chaining in Rust (Atomic With Gate Result)

**Date:** 2026-05-20
**Status:** Accepted
**Vector:** Safety

## Decision
The SHA-256 lineage hash is computed inside the Rust kernel,
atomically with the gate result. Python does not compute lineage hashes.

## Why
- Eliminates the gap between gate result and chain write
- No race condition possible — hash and result are one operation
- Blocked transactions are chained too — the record is complete
- Length-prefixed fields prevent concatenation collision attacks

## Consequences
- GateResponse includes new_lineage_hash — Python writes it to SQLite
- Python cannot forge a lineage hash without the Rust kernel

## Invariant
**Every transaction — approved or blocked — must be chained.**
**No gap between gate result and lineage record. Ever.**
