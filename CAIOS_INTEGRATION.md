# CAIOS / AETHEL Integration Boundary

## Purpose

This deployment branch treats CAIOS (from ELXaber/chaos-persona) as an external reasoning/orchestration component and AETHEL as the deterministic admission and lineage boundary.

## Boundary

CAIOS may propose, reason, classify, and produce agent outputs.

AETHEL decides whether a proposed transition is admissible.

The deployment path is:

CAIOS proposal -> agent outputs -> LQ scoring -> AETHEL Gate 0-3 -> lineage commit -> approved side effects

## Imported concepts

- CAIOS orchestration and epistemic-monitor concepts remain outside the normative AETHEL kernel.
- AETHEL's Rust/PyO3 safety kernel is the runtime enforcement boundary.
- Project-mono audit/invariant ideas are CI admission controls, not runtime constitutional semantics.

## Explicit non-imports

- No legacy CAIOS cryptographic/mesh code is copied into the AETHEL kernel.
- No floating-point CPOL/entropy computation is admitted into SPEC-004 normative paths.
- No legacy Undermoon physics validator is treated as SPEC-004 conformance code.

## Deployment invariant

The deterministic SPEC-004 kernel must remain independently testable without CAIOS, network services, Stripe, biometric infrastructure, or an LLM provider.

## Licensing / provenance

CAIOS source remains separately attributed to its upstream repository and license. This integration document records the architectural boundary; it does not relicense upstream CAIOS code.
