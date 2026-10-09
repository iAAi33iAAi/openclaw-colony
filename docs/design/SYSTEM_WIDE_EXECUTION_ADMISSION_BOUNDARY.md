# System-Wide Execution Admission Boundary
## Design Gate — Draft / Not Implemented / Do Not Enable Model-Assisted Execution

**Status:** DESIGN CANDIDATE  
**Scope:** OpenClaw Colony consequential state changes: payments, durable mutations, actuator/physical operations, privileged shell/tool execution, and other irreversible or high-impact effects.  
**Related:** [Issue #10](https://github.com/iAAi33iAAi/openclaw-colony/issues/10), [MVD-001 Intelligence Fabric PR #8](https://github.com/iAAi33iAAi/openclaw-colony/pull/8).

> This document specifies a design and verification gate. It does not implement or enable an execution boundary. The MVD-001 deny-all firewall is not currently wired into all existing Colony paths. Until ingress inventory and enforcement tests pass, treat model output as advisory only.

---

## 1. Security objective

No model proposal, tool result, API request, agent message, or orchestration decision may cause a consequential effect unless the actual effecting service independently verifies a valid, unexpired, unrevoked, single-use human-approval authorization bound to the exact action and evidence.

The enforcement point must be at the final trusted ingress that can perform the mutation—not solely in a UI, agent, orchestrator, caller adapter, prompt, or model.

The system must fail closed when authorization, identity, policy, replay protection, or durable audit dependencies are unavailable or ambiguous.

## 2. Non-goals

This design does **not**:
- authorize any payment, actuator, shell command, or state mutation;
- declare the current Colony transaction coordinator protected;
- treat `APPROVE_FOR_REVIEW` as approval to execute;
- accept free-form model-generated commands;
- claim canonical SPEC-004 / SPEC-005 / CPOL conformance;
- replace application-specific safety interlocks, legal controls, or independent review.

## 3. Threat model and trust assumptions

Assume model output and agent-produced content can be incorrect, manipulated, stale, or adversarial. Assume callers can bypass a UI and call internal APIs directly. Assume legacy routes, background workers, webhooks, retry handlers, and tool dispatchers may create side effects without traversing the newly introduced advisory service.

The design must resist:
- replay of a previously valid approval;
- mutation of an approved proposal after review;
- substitution of contract, model, target, operation, policy, or evidence after approval;
- privilege escalation through a different route or internal caller;
- reviewer identity spoofing or use of an untrusted key;
- duplicate effects caused by retries, timeouts, or concurrent requests;
- audit-store or nonce-store outage;
- stale policy, revoked reviewer key, expired approval, or rollback to old policy;
- confused-deputy behavior where a trusted service is induced to perform an action outside the reviewed scope.

Cryptographic verification depends on securely provisioned reviewer trust anchors, private-key custody, rotation/revocation, authenticated identity binding, and protected runtime configuration. These remain explicit deployment obligations.

## 4. Required ingress inventory

Before implementation, enumerate and trace every path that can cause consequential effects. Search results alone are insufficient: each candidate path must be traced to its final side-effecting function and tested.

Inventory at minimum:

1. Public and authenticated FastAPI routes, including `/process`, admin, payment, webhook, federation, and future routers.
2. `colony_coordinator.py` and `colony_coordinator_v2.py`, including action creation, state transitions, and `process_manna_payment()` or equivalent payment functions.
3. `backend/state_machine.py` and every state persistence adapter.
4. Agent orchestration, base-agent execution, background tasks, retry handlers, and internal service-to-service calls.
5. Tool dispatch, script execution, shell / PowerShell, filesystem write/delete, and MCP adapters.
6. Payment-provider webhooks, callbacks, refunds, and reconciliation paths.
7. Any actuator, device, industrial control, deployment, or privileged infrastructure adapters.
8. Test-only and maintenance endpoints that can mutate production state.

For each path record: entrypoint, authentication, authorization check, effecting function, data stores touched, external side effects, bypasses, and test identifier. An untraced path remains a blocker, not an assumed safe path.

## 5. Approval receipt: required semantics

A human approval receipt is a separate authorization artifact. It must be created only after an authenticated reviewer reviews the exact action and its supporting evidence. A model cannot create, sign, or self-assert this receipt.

The signed payload must bind at least:

- schema and policy version;
- unique receipt ID;
- immutable proposal-record digest;
- Knowledge Contract ID, version, and verified contract digest;
- model ID and verified model artifact digest;
- exact target/resource identifier;
- exact enumerated operation and typed, validated parameters;
- evidence bundle digest and references to authoritative evidence;
- authenticated reviewer subject and reviewer key ID;
- issued-at, not-before if used, expiry, and one-time nonce;
- required approval context, including the policy/risk class;
- audience / effecting service identity, preventing cross-service reuse.

Do not sign a display string and then execute separately parsed model text. The reviewed representation and executed typed action must be the same canonical object.

Unknown fields, ambiguous encodings, unsupported operations, missing binding values, duplicate keys, invalid timestamps, unrecognized policy versions, and noncanonical payloads must be rejected. The serialization/signature profile must be explicitly versioned and tested across implementations before it is described as canonical.

## 6. Approval lifecycle and verification order

The intended flow is:

1. **Propose:** model emits a typed advisory proposal; no side effect is possible.
2. **Resolve evidence:** trusted services load evidence by identifier and verify provenance, freshness, access rights, and digest. Model-provided evidence text is not authoritative.
3. **Normalize:** validate the requested operation against a versioned allowlist and convert it to a typed action. Reject free-form command strings.
4. **Review:** authenticated human reviewer sees the exact action, target, parameters, evidence summary, consequences, and policy version.
5. **Issue:** trusted approval service creates and signs a receipt over the immutable payload.
6. **Ingress verification:** the actual effecting service authenticates the caller and independently verifies signature, reviewer authority, audience, all digests, operation allowlist, expiry, revocation, policy version, and target.
7. **Atomic consume:** in the same durable coordination boundary as action admission, consume the nonce / receipt exactly once. Concurrent replay attempts must not both succeed.
8. **Commit effect:** execute only the exact typed operation that was reviewed. Use idempotency keys and transaction/outbox patterns where applicable; never re-interpret model prose.
9. **Audit:** persist a durable append-only admission decision and effect outcome. If required audit persistence cannot be guaranteed, do not execute.
10. **Reconcile:** independently compare authorization, admitted action, and resulting effect; record failures and compensation where supported.

The ordering of atomic receipt consumption and an external side effect requires careful design. A crash between those steps must not silently enable replay or cause duplicate effects. For external payments and physical operations, define idempotency, reconciliation, and recovery semantics per adapter before enabling it.

## 7. Typed operation allowlist and least privilege

Execution must use a finite, versioned operation registry. Each operation defines:
- stable operation identifier and schema version;
- allowed resource types and targets;
- typed parameter schema with strict bounds;
- required reviewer role / quorum, if applicable;
- risk class and expiry limits;
- required preconditions and independent interlocks;
- idempotency and recovery behavior;
- audit fields and expected effect evidence.

Unknown operation IDs, wildcard targets, arbitrary code, model-authored shell commands, and generic “execute this payload” operations are denied. The allowlist must be approved independently of model output. Physical/industrial operations must additionally retain hardware/process interlocks and domain-specific safety review.

## 8. Fail-closed conditions

Return a denial / hold without performing the effect if any of the following applies:
- receipt absent, malformed, unsigned, incorrectly signed, or signed by an untrusted/revoked reviewer;
- receipt expired, not yet valid, wrong audience, wrong policy version, or wrong target;
- proposal, contract, model, evidence, or operation digest differs from the reviewed receipt;
- operation is not on the current allowlist or parameters fail schema/range validation;
- nonce/receipt has already been consumed or replay store is unavailable;
- caller or reviewer identity cannot be authenticated;
- authoritative evidence, revocation, policy, or required audit storage is unavailable;
- admission/effect state is inconsistent or cannot be recovered safely.

A fallback mode must not convert any of these failures into implicit approval.

## 9. Required test gates

The following are merge blockers for an implementation PR. Tests must exercise the actual effecting ingress and assert that the side-effect spy / payment adapter / mutation store / actuator adapter was not called.

### Negative authorization tests
- No receipt; unsigned receipt; malformed signature; untrusted signer; revoked signer.
- Expired, future-dated, wrong-audience, wrong-policy, wrong-target receipt.
- Tampered proposal, contract digest/version, model digest, evidence digest, operation, or parameter after review.
- Unknown operation, wildcard target, malformed or out-of-range typed parameters.
- `APPROVE_FOR_REVIEW` proposal without a receipt.
- Valid receipt replayed sequentially and concurrently.
- Nonce/revocation/policy/audit store unavailable or returns corrupt data.
- Reviewer role revoked between receipt issue and admission.
- Legacy/internal route attempts to call the effecting function directly.
- Duplicate retry after timeout and crash at each transition boundary.

### Positive tests
- A valid receipt permits only the exact approved operation, target, and parameter set.
- A receipt for one target or operation cannot authorize another.
- Duplicate request returns a deterministic idempotent result without duplicate effects.
- Durable audit record correlates proposal, contract, model, reviewer, receipt, admitted action, and observed effect.
- Recovery reconciles crashes without replay or silent loss of audit.

### Coverage gate
Build a route-to-effect matrix from the inventory. Every identified side-effect path must have at least one test proving it is protected or explicitly disabled. Add a CI assertion that the inventory is complete and reviewed. A new effecting route without a corresponding admission test blocks merge.

## 10. Implementation sequencing

**Gate A — Inventory and design review:** complete the route-to-effect matrix; identify owners, data stores, external side effects, and bypass paths.

**Gate B — Pure verifier:** implement receipt parsing, canonical payload checks, signature verification, expiry/revocation, policy and allowlist evaluation without performing effects. Unit-test hostile inputs.

**Gate C — Durable admission store:** implement atomic one-time consumption, idempotency, durable audit, key lifecycle, and crash-recovery tests.

**Gate D — One isolated non-production adapter:** integrate a deliberately harmless, reversible test operation. Prove the real ingress cannot be bypassed. Do not begin with payments or actuators.

**Gate E — Route-by-route integration:** add enforcement at each inventoried effecting ingress, with negative tests for direct and legacy paths.

**Gate F — Independent review:** security review, operational recovery review, protocol review, and human sign-off. Keep model-assisted consequential execution disabled until all gates pass.

## 11. Evidence required to claim completion

A design document or green unit test suite alone does not prove system-wide enforcement. Completion requires:
- reviewed route-to-effect inventory;
- threat model and trust-anchor lifecycle;
- versioned receipt and serialization/signature profile;
- tested durable replay prevention and recovery;
- per-ingress negative and positive tests;
- CI evidence showing every inventoried effect path is covered;
- audit and reconciliation evidence from a non-production end-to-end run;
- independent review approval;
- explicit release decision identifying which operation classes remain disabled.

Until these are available, accurate status is: **execution admission design candidate; system-wide enforcement unproven; model-assisted consequential execution must remain disabled.**
