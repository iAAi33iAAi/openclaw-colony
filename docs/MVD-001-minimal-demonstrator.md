# AETHEL / CAIOS Minimal Demonstrator (MVD-001)

**Status:** Candidate implementation baseline  
**Operating mode:** Local inference, synthetic data, advisory only  
**Normative dependency:** SPEC-004 remains separately subject to canonical ratification.

## Objective

Demonstrate one factory-maintenance proposal flow in which a domain-bounded model produces structured recommendations, evidence is independently inspected, and deterministic policy returns APPROVE_FOR_REVIEW, HOLD, or REJECTED.

APPROVE_FOR_REVIEW is not execution authorization. This package has no actuator, payment, or mutation interface.

## Components

- `backend/intelligence_fabric/contracts.py`: strict Pydantic contracts, model manifest, telemetry, evidence, proposal and result schemas.
- `verification.py`: project-local JSON digest helper and explicit signature-verifier protocol. The default signature verifier rejects every signature.
- `evidence.py`: source/sensor allowlist, freshness, evidence quality, signature verification, and evidence lookup through an injected registry. Caller-supplied IDs are not treated as approved records.
- `policy.py`: provisional demo policy, not canonical SPEC-004/CPOL.
- `providers/ollama_provider.py`: local-loopback Ollama structured output; no cloud fallback.
- `service.py`: advisory orchestration and integrity-protected decision record.
- `api.py`: optional FastAPI router factory. The host must apply authentication before mounting it.

## Decision semantics

- APPROVE_FOR_REVIEW: contract, model, proposal, and evidence checks passed. Human review remains mandatory.
- HOLD: model or contract unavailable/unapproved, telemetry stale, signature unverified, or required evidence unresolved.
- REJECTED: proposal violates an explicit contract boundary, references unknown evidence, or targets an unauthorized asset.

## Important limitations

1. `AcceptSignature` in tests is a test double, not cryptography. Production must inject a real signature verifier backed by managed trust roots and key rotation/revocation.
2. Contract issuer-signature verification, durable revocation lookup, signed model manifests, and secure key management remain host responsibilities.
3. `canonical_json_bytes` is a project-local deterministic serialization profile, not a claim of RFC 8785 conformance.
4. `record_digest` is not a signature or proof of authorization.
5. The provider is restricted to local loopback URLs and disables environment proxy trust. Network isolation must still be configured by deployment.
6. The demo does not call the existing Colony transaction coordinator and must not be connected to payment or actuator routes.
7. The implementation does not compute or authorize using the provisional SPEC-004 metric. Do not claim canonical CPOL conformance from these tests.

## Run tests

From repository root, in an environment with backend requirements installed:

```bash
pytest -q tests/test_intelligence_fabric.py
```

## Before production

- Implement issuer-signature verification for Knowledge Contracts.
- Bind model identity to an artifact digest obtained from a trusted registry.
- Replace in-memory dictionaries with authenticated registries and revocation checks.
- Define canonical serialization and signature formats normatively.
- Add authenticated append-only evidence storage and independent verification.
- Mount the endpoint only behind application authentication and authorization.
- Complete security review, red-team testing, and independent SPEC-004 conformance.
