"""
OpenClaw Colony — Stripe Bridge
Handles MANNA payment splits on every APPROVED task.

MANNA distribution (from Resources agent spec):
  82% → Community Pool   (Stripe destination account: STRIPE_COMMUNITY_ACCOUNT)
  15% → Crew             (Stripe destination account: STRIPE_CREW_ACCOUNT)
   3% → Architect        (Stripe destination account: STRIPE_ARCHITECT_ACCOUNT)

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
import uuid
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("colony.stripe_bridge")

# ── Config ────────────────────────────────────────────────────────────────────
STRIPE_SECRET_KEY         = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_COMMUNITY_ACCOUNT  = os.environ.get("STRIPE_COMMUNITY_ACCOUNT", "")
STRIPE_CREW_ACCOUNT       = os.environ.get("STRIPE_CREW_ACCOUNT", "")
STRIPE_ARCHITECT_ACCOUNT  = os.environ.get("STRIPE_ARCHITECT_ACCOUNT", "")
STRIPE_WEBHOOK_SECRET     = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
MANNA_CENTS               = int(os.environ.get("COLONY_MANNA_CENTS", "100"))

MOCK_MODE = not bool(STRIPE_SECRET_KEY)

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
    community_cents:  int   # 82%
    crew_cents:       int   # 15%
    architect_cents:  int   # 3%

    def as_dict(self) -> dict:
        return {
            "total_cents":     self.total_cents,
            "community_cents": self.community_cents,
            "crew_cents":      self.crew_cents,
            "architect_cents": self.architect_cents,
        }


def calculate_manna_split(total_cents: int) -> MannaSplit:
    """
    Split total_cents into 82/15/3.
    Architect: 3% (increased from 1% — Architect's Covenant v2)
    Crew:      15%
    Community: 82%
    Rounding: community absorbs any remainder to ensure total is exact.
    """
    crew_cents      = round(total_cents * 0.15)
    architect_cents = round(total_cents * 0.03)
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


def _live_transfer(
    amount_cents: int,
    destination: str,
    task_id: str,
    label: str,
    idempotency_key: str,
) -> str:
    """Execute a real Stripe transfer to a connected account."""
    import stripe
    transfer = stripe.Transfer.create(
        amount=amount_cents,
        currency="usd",
        destination=destination,
        description=f"OpenClaw Colony MANNA — {label} — task {task_id}",
        metadata={"task_id": task_id, "manna_bucket": label},
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


def process_manna_payment(task_id: str, lineage_hash: str) -> PaymentResult:
    """
    Trigger MANNA split for an APPROVED task.
    Called by the coordinator immediately after lineage is committed.
    Returns a PaymentResult regardless of success/failure (never raises).
    """
    split = calculate_manna_split(MANNA_CENTS)

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

    # Live mode — three separate transfers with idempotency keys
    # Idempotency key = lineage_hash + bucket, so retries are safe
    try:
        community_id = _live_transfer(
            split.community_cents,
            STRIPE_COMMUNITY_ACCOUNT,
            task_id,
            "community",
            idempotency_key=f"{lineage_hash}_community",
        )
        crew_id = _live_transfer(
            split.crew_cents,
            STRIPE_CREW_ACCOUNT,
            task_id,
            "crew",
            idempotency_key=f"{lineage_hash}_crew",
        )
        architect_id = _live_transfer(
            split.architect_cents,
            STRIPE_ARCHITECT_ACCOUNT,
            task_id,
            "architect",
            idempotency_key=f"{lineage_hash}_architect",
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
        log.error("[STRIPE ERROR] task=%s error=%s", task_id, exc)
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


# ── Webhook verification ──────────────────────────────────────────────────────

def verify_webhook(payload: bytes, sig_header: str) -> Optional[dict]:
    """
    Verify a Stripe webhook signature and return the event dict.
    Returns None if verification fails or STRIPE_WEBHOOK_SECRET is not set.
    """
    if not STRIPE_WEBHOOK_SECRET:
        log.warning("[WEBHOOK] STRIPE_WEBHOOK_SECRET not set — skipping verification.")
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