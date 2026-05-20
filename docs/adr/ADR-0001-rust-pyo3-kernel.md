# ADR-0001: Rust PyO3 Kernel Over Python Fallback

**Date:** 2026-05-20
**Status:** Accepted
**Vector:** Safety

## Decision
The Aethel Safety Kernel runs as native Rust compiled via PyO3.
Python fallback exists but emits a warning and is never used in production.

## Why
- Constant-time HMAC comparison prevents timing attacks
- Memory isolation at hardware level prevents injection attacks
- Sub-millisecond gate evaluation regardless of Python GIL
- Panic = abort in release profile — no unwinding across FFI boundary

## Consequences
- Rust compiler required at build time (handled by Dockerfile)
- No Rust required on host machine
- Gate logic must be duplicated in Python fallback (kept in sync)

## Invariant
**This decision cannot be reversed without a full safety audit.**
