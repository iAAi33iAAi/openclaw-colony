"""Signed transfer admission tests. No test sends a real Stripe request."""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

import stripe_bridge
from db import SessionLocal, TransferAuthorizationNonce, init_db
from payment_admission import (
    issue_transfer_admission,
    verify_transfer_admission,
)

SECRET = "payment-admission-test-secret-at-least-32-bytes"
TASK_ID = "task-fixture-001"
LINEAGE_HASH = "a" * 64
APPROVAL_REF = "approval-record:1"
AMOUNT_CENTS = 100


@pytest.fixture
def db_session():
    init_db()
    session = SessionLocal()
    session.query(TransferAuthorizationNonce).delete()
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _admission(monkeypatch, *, task_id=TASK_ID, lineage_hash=LINEAGE_HASH, amount_cents=AMOUNT_CENTS, now_epoch=1_900_000_000):
    monkeypatch.setenv("COLONY_PAYMENT_ADMISSION_SECRET", SECRET)
    return issue_transfer_admission(
        decision="APPROVE",
        task_id=task_id,
        lineage_hash=lineage_hash,
        amount_cents=amount_cents,
        approval_ref=APPROVAL_REF,
        now_epoch=now_epoch,
    )


def test_receipt_is_bound_to_task_lineage_and_amount(db_session, monkeypatch):
    receipt = _admission(monkeypatch)
    ok, reason = verify_transfer_admission(
        db_session, receipt,
        task_id=TASK_ID,
        lineage_hash=LINEAGE_HASH,
        amount_cents=AMOUNT_CENTS,
        now_epoch=1_900_000_005,
    )
    assert ok is True
    assert reason == "OK"

    # The nonce has been claimed, so the same admission cannot be reused.
    replayed, replay_reason = verify_transfer_admission(
        db_session, receipt,
        task_id=TASK_ID,
        lineage_hash=LINEAGE_HASH,
        amount_cents=AMOUNT_CENTS,
        now_epoch=1_900_000_006,
    )
    assert replayed is False
    assert replay_reason == "admission_replayed"


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    [
        ("task_id", "other-task", "admission_task_or_lineage_mismatch"),
        ("lineage_hash", "b" * 64, "admission_task_or_lineage_mismatch"),
        ("amount_cents", 101, "admission_amount_mismatch"),
    ],
)
def test_receipt_cannot_be_retargeted(db_session, monkeypatch, field, value, expected_reason):
    receipt = _admission(monkeypatch)
    ok, reason = verify_transfer_admission(
        db_session, receipt,
        task_id=value if field == "task_id" else TASK_ID,
        lineage_hash=value if field == "lineage_hash" else LINEAGE_HASH,
        amount_cents=value if field == "amount_cents" else AMOUNT_CENTS,
        now_epoch=1_900_000_005,
    )
    assert ok is False
    assert reason == expected_reason
    assert db_session.query(TransferAuthorizationNonce).count() == 0


def test_modified_receipt_is_rejected(db_session, monkeypatch):
    receipt = _admission(monkeypatch)
    receipt["amount_cents"] = 9999
    ok, reason = verify_transfer_admission(
        db_session, receipt,
        task_id=TASK_ID,
        lineage_hash=LINEAGE_HASH,
        amount_cents=9999,
        now_epoch=1_900_000_005,
    )
    assert ok is False
    assert reason == "invalid_admission_signature"
    assert db_session.query(TransferAuthorizationNonce).count() == 0


def test_expired_receipt_is_rejected(db_session, monkeypatch):
    receipt = _admission(monkeypatch)
    ok, reason = verify_transfer_admission(
        db_session, receipt,
        task_id=TASK_ID,
        lineage_hash=LINEAGE_HASH,
        amount_cents=AMOUNT_CENTS,
        now_epoch=1_900_000_061,
    )
    assert ok is False
    assert reason == "admission_expired"


def test_issuer_requires_explicit_approval_and_persisted_reference(monkeypatch):
    monkeypatch.setenv("COLONY_PAYMENT_ADMISSION_SECRET", SECRET)
    with pytest.raises(ValueError, match="explicit APPROVE"):
        issue_transfer_admission(
            decision="REJECT",
            task_id=TASK_ID,
            lineage_hash=LINEAGE_HASH,
            amount_cents=AMOUNT_CENTS,
            approval_ref=APPROVAL_REF,
        )
    with pytest.raises(ValueError, match="approval record"):
        issue_transfer_admission(
            decision="APPROVE",
            task_id=TASK_ID,
            lineage_hash=LINEAGE_HASH,
            amount_cents=AMOUNT_CENTS,
            approval_ref="not-an-approval",
        )


def test_missing_signing_secret_blocks_admission(db_session, monkeypatch):
    monkeypatch.delenv("COLONY_PAYMENT_ADMISSION_SECRET", raising=False)
    ok, reason = verify_transfer_admission(
        db_session,
        None,
        task_id=TASK_ID,
        lineage_hash=LINEAGE_HASH,
        amount_cents=AMOUNT_CENTS,
        now_epoch=1_900_000_005,
    )
    assert ok is False
    assert reason == "payment_admission_not_configured"


def test_live_transfer_without_receipt_never_calls_stripe(db_session, monkeypatch):
    monkeypatch.setattr(stripe_bridge, "MOCK_MODE", False)
    monkeypatch.setenv("COLONY_LIVE_PAYMENTS_ENABLED", "true")
    monkeypatch.setenv("COLONY_PAYMENT_ADMISSION_SECRET", SECRET)
    transfer = MagicMock(side_effect=["tr_a", "tr_b", "tr_c"])
    monkeypatch.setattr(stripe_bridge, "_live_transfer", transfer)

    result = stripe_bridge.process_manna_payment(
        TASK_ID, LINEAGE_HASH, db=db_session
    )
    assert result.status == "failed"
    assert result.error.startswith("LIVE_TRANSFER_ADMISSION_REJECTED:")
    transfer.assert_not_called()


def test_live_transfer_requires_explicit_enable_flag(db_session, monkeypatch):
    monkeypatch.setattr(stripe_bridge, "MOCK_MODE", False)
    monkeypatch.setenv("COLONY_LIVE_PAYMENTS_ENABLED", "false")
    monkeypatch.setenv("COLONY_PAYMENT_ADMISSION_SECRET", SECRET)
    transfer = MagicMock(side_effect=["tr_a", "tr_b", "tr_c"])
    monkeypatch.setattr(stripe_bridge, "_live_transfer", transfer)
    receipt = _admission(monkeypatch)

    result = stripe_bridge.process_manna_payment(
        TASK_ID, LINEAGE_HASH, admission=receipt, db=db_session
    )
    assert result.status == "failed"
    assert result.error == "LIVE_PAYMENTS_DISABLED"
    transfer.assert_not_called()


def test_valid_admission_allows_only_the_bound_transfer_set(db_session, monkeypatch):
    monkeypatch.setattr(stripe_bridge, "MOCK_MODE", False)
    monkeypatch.setenv("COLONY_LIVE_PAYMENTS_ENABLED", "true")
    receipt = _admission(monkeypatch)
    transfer = MagicMock(side_effect=["tr_community", "tr_crew", "tr_architect"])
    monkeypatch.setattr(stripe_bridge, "_live_transfer", transfer)

    result = stripe_bridge.process_manna_payment(
        TASK_ID, LINEAGE_HASH, admission=receipt, db=db_session
    )
    assert result.status == "completed"
    assert transfer.call_count == 3
    assert result.community_id == "tr_community"
    assert result.crew_id == "tr_crew"
    assert result.architect_id == "tr_architect"

    replay_result = stripe_bridge.process_manna_payment(
        TASK_ID, LINEAGE_HASH, admission=receipt, db=db_session
    )
    assert replay_result.status == "failed"
    assert replay_result.error.endswith(":admission_replayed")
    assert transfer.call_count == 3
