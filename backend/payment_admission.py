"""Signed, task-bound authorization for live Stripe MANNA transfers.

Live transfers require an operator-approved task record plus a short-lived
HMAC receipt bound to its exact task ID, lineage hash and total amount.
The signing secret must be provisioned out-of-band and is never serialized.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SCHEMA = "aethel-transfer-admission/v1"
MAX_TTL_SECONDS = 60
_SECRET_ENV = "COLONY_PAYMENT_ADMISSION_SECRET"
_REQUIRED_FIELDS = {
    "schema",
    "decision",
    "task_id",
    "lineage_hash",
    "amount_cents",
    "currency",
    "approval_ref",
    "issued_at",
    "expires_at",
    "nonce",
}


def _configured_secret() -> str:
    return os.environ.get(_SECRET_ENV, "")


def is_transfer_admission_configured() -> bool:
    return len(_configured_secret().encode("utf-8")) >= 32


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sign(payload: dict[str, Any], secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        _canonical(payload),
        hashlib.sha256,
    ).hexdigest()


def issue_transfer_admission(
    *,
    decision: str,
    task_id: str,
    lineage_hash: str,
    amount_cents: int,
    approval_ref: str,
    now_epoch: int | None = None,
) -> dict[str, Any]:
    """Mint a short-lived receipt only for the approved admin-queue path."""
    secret = _configured_secret()
    if len(secret.encode("utf-8")) < 32:
        raise RuntimeError(f"{_SECRET_ENV} must contain at least 32 UTF-8 bytes")
    if decision != "APPROVE":
        raise ValueError("transfer authorization requires an explicit APPROVE decision")
    if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 128:
        raise ValueError("task_id is missing or invalid")
    if not isinstance(lineage_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", lineage_hash):
        raise ValueError("lineage_hash must be a lowercase 64-character SHA-256 digest")
    if not isinstance(amount_cents, int) or isinstance(amount_cents, bool) or amount_cents <= 0:
        raise ValueError("amount_cents must be a positive integer")
    if not isinstance(approval_ref, str) or not re.fullmatch(r"approval-record:[1-9][0-9]*", approval_ref):
        raise ValueError("approval_ref must identify a persisted approval record")

    issued_at = int(time.time()) if now_epoch is None else int(now_epoch)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "decision": "APPROVE",
        "task_id": task_id,
        "lineage_hash": lineage_hash,
        "amount_cents": amount_cents,
        "currency": "usd",
        "approval_ref": approval_ref,
        "issued_at": issued_at,
        "expires_at": issued_at + MAX_TTL_SECONDS,
        "nonce": secrets.token_urlsafe(24),
    }
    payload["signature"] = _sign(payload, secret)
    return payload


def verify_transfer_admission(
    db: Session | None,
    admission: Any,
    *,
    task_id: str,
    lineage_hash: str,
    amount_cents: int,
    now_epoch: int | None = None,
    secret: str | None = None,
) -> tuple[bool, str]:
    """Verify and atomically claim a task-scoped admission receipt; fail closed."""
    key = _configured_secret() if secret is None else secret
    if not isinstance(key, str) or len(key.encode("utf-8")) < 32:
        return False, "payment_admission_not_configured"
    if not isinstance(admission, dict):
        return False, "signed_admission_required"
    if set(admission.keys()) != _REQUIRED_FIELDS | {"signature"}:
        return False, "admission_schema_mismatch"

    signature = admission.get("signature")
    if not isinstance(signature, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", signature):
        return False, "invalid_admission_signature"
    payload = {key_name: value for key_name, value in admission.items() if key_name != "signature"}
    try:
        expected = _sign(payload, key)
    except (TypeError, ValueError):
        return False, "invalid_admission_payload"
    if not hmac.compare_digest(signature.lower(), expected):
        return False, "invalid_admission_signature"

    if payload.get("schema") != SCHEMA or payload.get("decision") != "APPROVE":
        return False, "admission_decision_not_approved"
    if payload.get("task_id") != task_id or payload.get("lineage_hash") != lineage_hash:
        return False, "admission_task_or_lineage_mismatch"
    if payload.get("amount_cents") != amount_cents or isinstance(payload.get("amount_cents"), bool):
        return False, "admission_amount_mismatch"
    if payload.get("currency") != "usd":
        return False, "admission_currency_mismatch"
    if not isinstance(payload.get("approval_ref"), str) or not re.fullmatch(
        r"approval-record:[1-9][0-9]*", payload["approval_ref"]
    ):
        return False, "admission_approval_reference_missing"

    issued_at = payload.get("issued_at")
    expires_at = payload.get("expires_at")
    nonce = payload.get("nonce")
    if (
        not isinstance(issued_at, int)
        or isinstance(issued_at, bool)
        or not isinstance(expires_at, int)
        or isinstance(expires_at, bool)
        or not isinstance(nonce, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", nonce)
    ):
        return False, "admission_time_or_nonce_malformed"

    now_value = int(time.time()) if now_epoch is None else int(now_epoch)
    if issued_at > now_value + 5:
        return False, "admission_issued_in_future"
    if expires_at <= now_value:
        return False, "admission_expired"
    if expires_at <= issued_at or expires_at - issued_at > MAX_TTL_SECONDS:
        return False, "admission_lifetime_invalid"

    if db is None:
        return False, "admission_nonce_store_unavailable"
    try:
        # Keep this module's import side-effect-free for lightweight callers
        # (e.g. covenant/split checks) that do not install the ORM layer.
        from sqlalchemy.exc import IntegrityError
        from db import TransferAuthorizationNonce
    except ImportError:
        return False, "admission_nonce_store_unavailable"

    nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    try:
        db.add(
            TransferAuthorizationNonce(
                nonce_hash=nonce_hash,
                task_id=task_id,
                lineage_hash=lineage_hash,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        return False, "admission_replayed"
    except Exception:
        db.rollback()
        return False, "admission_nonce_store_unavailable"

    return True, "OK"
