# ADR-0004: Formal State Machine for Node Lifecycle

**Date:** 2026-05-20
**Status:** Accepted
**Vector:** Safety + Sovereignty

## Decision
NodeState, ProposalState, and TransactionState are formally defined
with explicit transition tables. Invalid transitions are rejected.

## Why
- Prevents desynchronization in the federation (Laminar Flow)
- SYNCING→LIVE guarded by Lineage Head Check
- Proposals cannot be approved after expiry
- Transactions cannot skip gates

## Consequences
- state_machine.py is a first-class module, not a utility
- All state changes go through transition() — never direct assignment
- 56 dedicated tests cover all transition paths

## Invariant
**A node cannot claim LIVE status until its lineage tip matches peers.**
**This guard cannot be bypassed.**
