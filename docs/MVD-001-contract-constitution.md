# MVD-001 Knowledge Contract Constitution

**Status:** Candidate implementation rule set; not canonical AETHEL SPEC-004 or CPOL.  
**Scope:** Factory-maintenance advisory inference only.  
**Default posture:** Deny unless every precondition is positively verified.

## Authority hierarchy

1. **Host trust configuration** defines accepted issuer public keys and revoked key IDs. A contract cannot add its own trust anchor.
2. **Signed Knowledge Contract** defines the permitted domain, agent, model digests, evidence sources, sensors, targets, recommendation types, telemetry freshness, minimum evidence quality, expiration, and policy identifier.
3. **Runtime policy and evidence inspection** validate the request against that contract before model inference.
4. **Domain SLM** creates a typed recommendation only. Its text, confidence, and claims of authority never grant permissions.
5. **Human review and execution authorization** are separate future control planes. MVD-001 exposes no actuator, payment, or mutation operation.

Lower layers cannot widen permissions established by higher layers.

## Contract-signing profile

The candidate profile uses an Ed25519 signature over a version-tagged payload containing the signer key ID, UTC issue timestamp, and SHA-256 digest of the normalized Knowledge Contract. Set-valued fields are serialized as sorted arrays before digest calculation. The signature field itself is excluded from the signed payload.

The verifier must reject unknown or revoked issuer IDs, malformed trust anchors, malformed signatures, signature mismatches, issue timestamps outside the configured future-clock tolerance, or contracts whose issue time is at or after their expiry. Contract expiration and the contract's revocation flag are checked by runtime policy on each request.

The trust-anchor map is a host-provisioned snapshot. The service does not retrieve keys from the contract, infer trust from a model response, or silently accept an unsigned contract. The candidate JSON serialization profile is project-local and must not be called RFC 8785 or a ratified cross-language canonical format.

## Request-admission invariants

A proposal may reach the SLM only if all of the following hold:

- The Knowledge Contract signature verifies against a host-configured, non-revoked key.
- The contract is not revoked and has not expired.
- The exact requested model ID resolves to an approved manifest whose digest is allowed by the contract.
- The local Ollama runtime reports exactly one matching model tag with the approved digest.
- The requested target is contract-allowed and matches the telemetry target.
- Telemetry is signed by a verifier accepted by the host, uses a permitted sensor, and is within the configured freshness window.
- Every evidence reference resolves through the injected evidence registry to an approved record, from an approved source, meeting the quality floor.
- No failed admission check is converted into prompt text or handed to the model for reinterpretation.

If a condition fails, inference is not called and the decision is HOLD or REJECTED, unless contract-authentication itself fails, in which case the service raises a trust error and the API host must fail closed.

## Post-inference invariants

- Output is parsed as the strict Proposal schema; unknown fields are rejected.
- Recommendation type, domain, contract version, target, and evidence references are checked independently of the model.
- Human review is mandatory; requires_human_review=false is invalid.
- The runtime-reported model digest is checked again after generation; output is discarded if it changed or cannot be rechecked.
- A decision record includes the contract digest and a deterministic record digest.
- A digest provides integrity comparison only; it is not a signature, a proof of signer identity, or execution authorization.

## Decision meanings

| Decision | Meaning | Permitted consequence |
|---|---|---|
| APPROVE_FOR_REVIEW | Evidence, runtime, and proposal checks passed | Display or queue for human review only |
| HOLD | Required trust, freshness, availability, or admission fact is missing or unverified | No action; resolve the named hold reason |
| REJECTED | Request or proposal violates an explicit boundary | No action; record rejection |

No decision produced by this service means "execute", "pay", "shutdown", "write", or "authorize."

## Minimum conformance vectors

The test suite must prove these deny cases without calling inference: tampered contract; untrusted issuer; revoked issuer; future-issued contract; unknown model; unapproved model digest; runtime digest mismatch; changed runtime digest during inference; stale telemetry; invalid telemetry signature; unapproved evidence; fabricated evidence reference; target mismatch; target outside scope; schema violation; and removal of the human-review requirement.

Positive vectors must prove that (a) a trusted signed contract verifies, (b) an approved runtime digest permits the advisory inference path, and (c) the only positive terminal decision remains APPROVE_FOR_REVIEW.

## Explicit non-goals and deployment gates

This candidate does not implement the canonical SPEC-004 metric, CPOL conformance, durable append-only evidence storage, production telemetry signing keys, independent model-file attestation, measured boot, immutable Ollama tags, authenticated reviewer attestations, a replay-resistant human approval service, or any actuator/payment integration. Each is a separate gate. The financial allocation disagreement is also separate; this module must not be treated as its resolution.
