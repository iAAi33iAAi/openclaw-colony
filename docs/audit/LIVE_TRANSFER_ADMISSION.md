# Live Transfer Admission Boundary

Status: draft remediation; do not enable real transfers until the external trust model and deployment are reviewed.

## Threat addressed

An internal caller invokes the live Stripe bridge with only a task ID and lineage hash, without proving that the exact task passed the durable human-approval path.

## Implemented application boundary

- The live transfer rail defaults to disabled and requires \`COLONY_LIVE_PAYMENTS_ENABLED=true\`.
- When Stripe is configured for live processing, new tasks are forced through the durable operator approval queue.
- The approval endpoint refuses to create lineage or attempt transfers if live processing is disabled or the admission secret is absent.
- The bridge requires a short-lived HMAC-SHA256 receipt bound to the exact task ID, SHA-256 lineage hash, total amount in cents, USD currency, decision \`APPROVE\`, and a persisted approval-record reference.
- The receipt lifetime is at most 60 seconds. A unique nonce is durably claimed before the bridge calls Stripe. Stripe idempotency keys remain bound to lineage and bucket.
- Unit tests mock the transfer helper. They never send a real Stripe API request.

## Required environment configuration

- \`COLONY_LIVE_PAYMENTS_ENABLED=false\` is the safe default.
- \`COLONY_PAYMENT_ADMISSION_SECRET\` must be provisioned out-of-band and contain at least 32 UTF-8 bytes.
- \`STRIPE_SECRET_KEY\` and connected account IDs are not to be stored in this file or in source control.
- A deployment needs verified human approval, Stripe connected-account configuration, TLS, reconciliation procedures and test evidence before any live flag change.

## Trust boundary and residual risk

The current signer and verifier both run inside the same application process. This catches missing, stale, replayed or retargeted unsigned admissions at the payment bridge, but it is not an independent HSM-backed approval authority. A full process compromise or admission-secret disclosure could forge a receipt. Treat this as an application-level defense-in-depth measure, not as proof that production treasury authorization is complete.

There is also a partial-transfer case: if one or two of the three bucket transfers succeed and a later one fails, do not blindly retry. Reconcile Stripe transfer IDs and ledger state before further action; the one-use receipt deliberately cannot authorize a second attempt.

## Release gate

Keep the live rail off until the signing authority is moved to or independently validated by an appropriate trusted boundary, the scanner and payment deployment secrets are provisioned and rotated safely, CI passes, and finance/security reviewers sign off.
