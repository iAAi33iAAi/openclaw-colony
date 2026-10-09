# AETHEL / CAIOS Minimal Demonstrator (MVD-001)

**Status:** Candidate implementation baseline  
**Operating mode:** Local inference, synthetic data, advisory only  
**Normative dependency:** SPEC-004 remains separately subject to canonical ratification.

## Objective

Demonstrate one factory-maintenance proposal flow in which a domain-bounded model produces structured recommendations, evidence is independently inspected, and deterministic policy returns APPROVE_FOR_REVIEW, HOLD, or REJECTED.

APPROVE_FOR_REVIEW is not execution authorization. This package has no actuator, payment, or mutation interface.

## Components

- `backend/intelligence_fabric/contracts.py`: strict Pydantic schemas, including the signed Knowledge Contract envelope and contract-digest-bound result.
- `contract_trust.py`: Ed25519 signature verification against host-configured public-key trust anchors, signer revocation IDs, stable set ordering, and canonical contract digests.
- `verification.py`: project-local JSON digest helper and telemetry signature-verifier protocol. The default telemetry signature verifier rejects every signature.
- `evidence.py`: source/sensor allowlist, freshness, evidence quality, signature verification, and evidence lookup through an injected registry. Caller-supplied IDs are not treated as approved records.
- `policy.py`: provisional demo policy, not canonical SPEC-004/CPOL.
- `providers/ollama_provider.py`: local-loopback Ollama structured output; no cloud fallback. It checks the exact model tag and runtime-reported digest before and after inference.
- `service.py`: advisory orchestration and integrity-protected decision record.
- `api.py`: optional FastAPI router factory. The host must apply authentication before mounting it.

## Decision semantics

- APPROVE_FOR_REVIEW: contract, model, proposal, and evidence checks passed. Human review remains mandatory.
- HOLD: model or contract unavailable/unapproved, telemetry stale, signature unverified, or required evidence unresolved.
- REJECTED: proposal violates an explicit contract boundary, references unknown evidence, or targets an unauthorized asset.

## Important limitations

1. `AcceptSignature` in tests is a test double, not cryptography. Production must inject a real signature verifier backed by managed trust roots and key rotation/revocation.
2. Contract issuer signatures are now verified by `contract_trust.py` against explicitly supplied host trust anchors. Production still requires protected trust-store provisioning, durable key revocation and rotation, private-key custody, and secure boot-time configuration. The trust-anchor snapshot is supplied by the host; the envelope cannot introduce its own key.
3. `canonical_json_bytes` is a project-local deterministic serialization profile, not a claim of RFC 8785 conformance.
4. `record_digest` is not a signature or proof of authorization.
5. The provider is restricted to a local loopback origin and disables environment proxy trust. Model identity is compared against the digest returned by the local Ollama `/api/tags` endpoint both before and after generation; this is runtime-reported identity, not independent file attestation or measured boot. A tag can still be changed between checks, so the host must protect the model store and runtime from concurrent administrative modification. Network isolation must still be configured by deployment.
6. The demo does not call the existing Colony transaction coordinator and must not be connected to payment or actuator routes.
7. The implementation does not compute or authorize using the provisional SPEC-004 metric. Do not claim canonical CPOL conformance from these tests.
8. The signed contract payload is a project-local versioned profile built on deterministic JSON; it is not claimed to implement RFC 8785 or a ratified AETHEL serialization standard.
9. Runtime identity checks narrow the tag-substitution window but cannot eliminate a concurrent runtime/model-store race. The deployment must prevent untrusted actors from modifying Ollama state during inference.

## Run tests

From repository root, in an environment with backend requirements installed:

```bash
pytest -q tests/test_intelligence_fabric.py
```

## Before production

- Provision and rotate issuer trust anchors, connect key revocation to a durable source, and protect issuer private keys.
- Ratify the signed-envelope canonicalization profile and add cross-language golden vectors.
- Bind model identity to an artifact digest approved by the contract and compared to runtime-reported Ollama tags; add host controls for immutable or locked model tags during inference.
- Replace in-memory dictionaries with authenticated registries and revocation checks.
- Define canonical serialization and signature formats normatively.
- Add authenticated append-only evidence storage and independent verification.
- Mount the endpoint only behind application authentication and authorization.
- Complete security review, red-team testing, and independent SPEC-004 conformance.
