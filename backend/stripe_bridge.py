"""
OpenClaw Colony — Stripe Bridge
Handles MANNA payment splits on every APPROVED task.

MANNA distribution (from Resources agent spec):
  84% → Community Pool   (Stripe destination account: STRIPE_COMMUNITY_ACCOUNT)
  15% → Crew             (Stripe destination account: STRIPE_CREW_ACCOUNT)
   1% → Architect        (Stripe destination account: STRIPE_ARCHITECT_ACCOUNT)

Environment variables required for live mode:
  STRIPE_SECRET_KEY          sk_live_... or sk_test_...
  STRIPE_COMMUNITY_ACCOUNT   acct_...
  STRIPE_CREW_ACCOUNT        acct_...
  STRIPE_ARCHITECT_ACCOUNT   acct_...
  STRIPE_WEBHOOK_SECRET      whsec_...
  COLONY_MANNA_CENTS         integer, default 100 (= $1.00 per approved task)

If STRIPE_SECRET_KEY is not set, the bridge runs in MOCK mode:
  - All splits are logged and recorded in the DB but no real Stripe calls are made.
  - stripe_transfer_id will be "mock_<uuid>" in payment records.
"""

import logging
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from execution_admission import verify_execution_admission

log = logging.getLogger("colony.stripe_bridge")

# ── Config ────────────────────────────────────────────────────────────────────
STRIPE_SECRET_KEY         = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_COMMUNITY_ACCOUNT  = os.environ.get("STRIPE_COMMUNITY_ACCOUNT", "")
STRIPE_CREW_ACCOUNT       = os.environ.get("STRIPE_CREW_ACCOUNT", "")
STRIPE_ARCHITECT_ACCOUNT  = os.environ.get("STRIPE_ARCHITECT_ACCOUNT", "")
STRIPE_WEBHOOK_SECRET     = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
MANNA_CENTS               = int(os.environ.get("COLONY_MANNA_CENTS", "100"))

MOCK_MODE = not bool(STRIPE_SECRET_KEY)

def validate_payment_mode() -> None:
    """Fail closed on incomplete live-payment configuration."""
    environment = os.environ.get("COLONY_ENV", "").strip().lower()
    if MOCK_MODE and environment == "production":
        raise RuntimeError(
            "STRIPE_SECRET_KEY must be configured in production; "
            "mock MANNA transfers are not permitted."
        )
    if not MOCK_MODE:
        accounts = {
            "community": STRIPE_COMMUNITY_ACCOUNT,
            "crew": STRIPE_CREW_ACCOUNT,
            "architect": STRIPE_ARCHITECT_ACCOUNT,
        }
        invalid = [name for name, account in accounts.items()
                   if not isinstance(account, str) or not account.startswith("acct_")]
        if invalid:
            raise RuntimeError(
                "Live Stripe transfers require valid connected account IDs for: "
                + ", ".join(invalid)
            )
        admission_key = os.environ.get("COLONY_EXECUTION_ADMISSION_SECRET", "")
        biometric_key = os.environ.get("COLONY_BAS_SECRET", "")
        if len(admission_key) < 32 or (
            biometric_key and admission_key == biometric_key
        ):
            raise RuntimeError(
                "Live Stripe transfers require a distinct "
                "COLONY_EXECUTION_ADMISSION_SECRET of at least 32 characters."
            )


if MOCK_MODE:
    log.warning(
        "[STRIPE] STRIPE_SECRET_KEY not set — running in MOCK mode. "
        "No real payments will be processed."
    )
else:
    import stripe as _stripe
    _stripe.api_key = STRIPE_SECRET_KEY
    log.info("[STRIPE] Live mode active. MANNA_CENTS=%d", MANNA_CENTS)


# ── MANNA split calculator ────────────────────────────────────────────────────

@dataclass
class MannaSplit:
    total_cents:      int
    community_cents:  int   # 84%
    crew_cents:       int   # 15%
    architect_cents:  int   # 1%

    def as_dict(self) -> dict:
        return {
            "total_cents":     self.total_cents,
            "community_cents": self.community_cents,
            "crew_cents":      self.crew_cents,
            "architect_cents": self.architect_cents,
        }


def calculate_manna_split(total_cents: int) -> MannaSplit:
    """
    Split total_cents into 84/15/1.
    Architect: 1% (binding Architect's Covenant)
    Crew:      15%
    Community: 84%
    Rounding: community absorbs any remainder to ensure total is exact.
    """
    crew_cents      = round(total_cents * 0.15)
    architect_cents = round(total_cents * 0.01)
    community_cents = total_cents - crew_cents - architect_cents
    return MannaSplit(
        total_cents=total_cents,
        community_cents=community_cents,
        crew_cents=crew_cents,
        architect_cents=architect_cents,
    )


# ── Transfer helpers ──────────────────────────────────────────────────────────

def _mock_transfer(amount_cents: int, destination: str, task_id: str, label: str) -> str:
    """Simulate a Stripe transfer in mock mode."""
    mock_id = f"mock_{uuid.uuid4().hex[:12]}"
    log.info(
        "[MOCK TRANSFER] %s → %s  amount=%d cents  task=%s  id=%s",
        label, destination or "unset", amount_cents, task_id, mock_id,
    )
    return mock_id


def build_payment_admission_claims(task_id: str, lineage_hash: str) -> dict[str, Any]:
    """Build the exact values a live transfer receipt must authorize."""
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id is required for payment admission.")
    if (
        not isinstance(lineage_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", lineage_hash) is None
    ):
        raise ValueError("lineage_hash must be a 64-character SHA-256 digest.")
    split = calculate_manna_split(MANNA_CENTS)
    return {
        "schema": "colony-manna-payment-claims/v1",
        "task_id": task_id,
        "lineage_hash": lineage_hash,
        "currency": "usd",
        "total_cents": split.total_cents,
        "split": split.as_dict(),
        "destinations": {
            "community": STRIPE_COMMUNITY_ACCOUNT,
            "crew": STRIPE_CREW_ACCOUNT,
            "architect": STRIPE_ARCHITECT_ACCOUNT,
        },
    }


def _live_transfer(
    amount_cents: int,
    destination: str,
    task_id: str,
    label: str,
    idempotency_key: str,
    admission_receipt: dict | None = None,
) -> str:
    """Execute a real transfer only when a signed admission binds this exact payment."""
    if label not in {"community", "crew", "architect"}:
        raise RuntimeError("Unsupported MANNA bucket.")
    try:
        lineage_hash = idempotency_key.rsplit("_", 1)[0]
        expected_claims = build_payment_admission_claims(task_id, lineage_hash)
    except (TypeError, ValueError):
        raise RuntimeError("Payment identifiers are invalid; transfer denied.") from None
    valid, reason = verify_execution_admission(admission_receipt, expected_claims)
    if not valid:
        log.error("[STRIPE] Refusing live transfer without valid AETHEL admission: %s", reason)
        raise RuntimeError("Live transfer denied: signed AETHEL execution admission is invalid.")
    expected_amount = expected_claims["split"].get(f"{label}_cents")
    expected_destination = expected_claims["destinations"].get(label)
    if amount_cents != expected_amount or destination != expected_destination:
        log.error("[STRIPE] Transfer parameters do not match admitted %s bucket.", label)
        raise RuntimeError("Live transfer denied: amount or destination differs from admission.")

    import stripe
    transfer = stripe.Transfer.create(
        amount=amount_cents,
        currency="usd",
        destination=destination,
        description=f"OpenClaw Colony MANNA — {label} — task {task_id}",
        metadata={"task_id": task_id, "manna_bucket": label, "lineage_hash": lineage_hash},
        idempotency_key=idempotency_key,
    )
    log.info(
        "[STRIPE TRANSFER] %s → %s  amount=%d cents  id=%s",
        label, destination, amount_cents, transfer.id,
    )
    return transfer.id


# ── Main entry point ──────────────────────────────────────────────────────────

@dataclass
class PaymentResult:
    task_id:            str
    lineage_hash:       str
    split:              MannaSplit
    community_id:       Optional[str]
    crew_id:            Optional[str]
    architect_id:       Optional[str]
    status:             str   # "completed" | "mock" | "failed"
    error:              Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "task_id":        self.task_id,
            "lineage_hash":   self.lineage_hash,
            "split":          self.split.as_dict(),
            "community_id":   self.community_id,
            "crew_id":        self.crew_id,
            "architect_id":   self.architect_id,
            "status":         self.status,
            "error":          self.error,
        }


def process_manna_payment(
    task_id: str,
    lineage_hash: str,
    admission_receipt: dict | None = None,
) -> PaymentResult:
    """
    Trigger the MANNA split. Mock mode never moves real money. Live mode requires
    a signed, fresh AETHEL execution-admission receipt bound to the task, lineage,
    amounts, currency and destinations. Missing/invalid admission fails closed.
    """
    split = calculate_manna_split(MANNA_CENTS)
    try:
        validate_payment_mode()
    except Exception as exc:
        return PaymentResult(
            task_id=task_id,
            lineage_hash=lineage_hash,
            split=split,
            community_id=None,
            crew_id=None,
            architect_id=None,
            status="failed",
            error=str(exc),
        )

    if MOCK_MODE:
        return PaymentResult(
            task_id=task_id,
            lineage_hash=lineage_hash,
            split=split,
            community_id=_mock_transfer(split.community_cents, STRIPE_COMMUNITY_ACCOUNT, task_id, "community"),
            crew_id=_mock_transfer(split.crew_cents, STRIPE_CREW_ACCOUNT, task_id, "crew"),
            architect_id=_mock_transfer(split.architect_cents, STRIPE_ARCHITECT_ACCOUNT, task_id, "architect"),
            status="mock",
        )

    # Live mode — validate the receipt before any transfer call. Each actual
    # Stripe call re-verifies the same receipt and the exact bucket amount/destination.
    try:
        expected_claims = build_payment_admission_claims(task_id, lineage_hash)
        valid, reason = verify_execution_admission(admission_receipt, expected_claims)
    except Exception as exc:
        valid, reason = False, str(exc)
    if not valid:
        log.error("[STRIPE] Live MANNA split denied before execution: %s", reason)
        return PaymentResult(
            task_id=task_id,
            lineage_hash=lineage_hash,
            split=split,
            community_id=None,
            crew_id=None,
            architect_id=None,
            status="failed",
            error="Live transfer denied: signed AETHEL execution admission is invalid.",
        )

    # Idempotency key = lineage_hash + bucket, so retries are safe
    community_id = None
    crew_id = None
    architect_id = None
    try:
        community_id = _live_transfer(
            split.community_cents,
            STRIPE_COMMUNITY_ACCOUNT,
            task_id,
            "community",
            idempotency_key=f"{lineage_hash}_community",
            admission_receipt=admission_receipt,
        )
        crew_id = _live_transfer(
            split.crew_cents,
            STRIPE_CREW_ACCOUNT,
            task_id,
            "crew",
            idempotency_key=f"{lineage_hash}_crew",
            admission_receipt=admission_receipt,
        )
        architect_id = _live_transfer(
            split.architect_cents,
            STRIPE_ARCHITECT_ACCOUNT,
            task_id,
            "architect",
            idempotency_key=f"{lineage_hash}_architect",
            admission_receipt=admission_receipt,
        )
        return PaymentResult(
            task_id=task_id,
            lineage_hash=lineage_hash,
            split=split,
            community_id=community_id,
            crew_id=crew_id,
            architect_id=architect_id,
            status="completed",
        )

    except Exception as exc:
        log.error(
            "[STRIPE ERROR] task=%s error=%s community=%s crew=%s architect=%s",
            task_id,
            exc,
            community_id,
            crew_id,
            architect_id,
        )
        return PaymentResult(
            task_id=task_id,
            lineage_hash=lineage_hash,
            split=split,
            community_id=community_id,
            crew_id=crew_id,
            architect_id=architect_id,
            status="failed",
            error=str(exc),
        )


# ── Webhook verification ──────────────────────────────────────────────────────

def verify_webhook(payload: bytes, sig_header: str) -> Optional[dict]:
    """
    Verify a Stripe webhook signature and return the event dict.
    Returns None if verification fails or STRIPE_WEBHOOK_SECRET is not set.
    """
    if not STRIPE_WEBHOOK_SECRET:
        # Never accept unsigned webhooks in normal operation. An explicit,
        # separately named dev-only flag is required for local/mock testing.
        dev_mode = os.environ.get("COLONY_DEV_MODE", "").lower() == "true"
        allow_unverified = os.environ.get(
            "COLONY_ALLOW_UNVERIFIED_WEBHOOKS", ""
        ).lower() == "true"
        if not (dev_mode and allow_unverified):
            log.error(
                "[WEBHOOK] STRIPE_WEBHOOK_SECRET missing — rejecting unsigned webhook."
            )
            return None
        log.warning(
            "[WEBHOOK] unsigned webhook accepted only because explicit dev override is enabled."
        )
        import json
        try:
            return json.loads(payload)
        except Exception:
            return None

    try:
        import stripe
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
        return dict(event)
    except Exception as exc:
        log.warning("[WEBHOOK] Signature verification failed: %s", exc)
        return None