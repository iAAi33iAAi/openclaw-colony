# ADR-0002: SQLite Over PostgreSQL for Node-Local Chain

**Date:** 2026-05-20
**Status:** Accepted
**Vector:** Sovereignty

## Decision
Each node stores its lineage chain in SQLite with WAL mode enabled.

## Why
- Zero external dependencies — no database server required
- WAL mode enables concurrent reads without blocking writes
- Portable — the entire chain is one file, trivially backed up
- Sovereignty — no external database that can be taken down

## Consequences
- Not suitable for multi-writer scenarios (single node writes)
- Migration path to PostgreSQL exists if needed (same SQLAlchemy models)

## Invariant
**The chain must be portable. One file. Self-contained. Always.**
