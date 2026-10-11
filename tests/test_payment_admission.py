"""Regression tests for signed admission at the live payment boundary."""
import os
import sys

import pytest

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
ORCHESTRATOR = os.path.join(BACKEND, "colony-agents", "orchestrator")
for path in (BACKEND, ORCHESTRATOR):
    if path not in sys.path:
        sys.path.insert(0, path)

import stripe_bridge as payments
from execution_admission import issue_execution_admission, verify_execution_admission


def _approved_result():
    return {
        "verdict": "APPROVED",
        "gates": {
            "gate_0": {"verdict": "PASS", "reason": None},
            "gate_1": {"verdict": "PASS", "reason": None},
            "gate_2": {"verdict": "PASS", "reason": None},
            "gate_3": {"verdict": "PASS", "reason": None},
        },
    }


def _configure_live(monkeypatch):
    monkeypatch.setattr(payments, "MOCK_MODE", False)
    monkeypatch.setattr(payments, "STRIPE_SECRET_KEY", "sk_test_placeholder_for_unit_test")
    monkeypatch.setattr(payments, "STRIPE_COMMUNITY_ACCOUNT", "acct_community123")
    monkeypatch.setattr(payments, "STRIPE_CREW_ACCOUNT", "acct_crew123")
    monkeypatch.setattr(payments, "STRIPE_ARCHITECT_ACCOUNT", "acct_architect123")
    monkeypatch.setenv("COLONY_ENV", "test")
    monkeypatch.setenv("COLONY_EXECUTION_ADMISSION_SECRET", "execution-admission-test-" + "x" * 40)
    monkeypatch.delenv("COLONY_BAS_SECRET", raising=False)


def test_admission_issued_only_for_all_four_passed_gates(monkeypatch):
    _configure_live(monkeypatch)
    claims = payments.build_payment_admission_claims("task-001", "a" * 64)
    receipt = issue_execution_admission(_approved_result(), claims)
    assert receipt["payload"]["decision"] == "APPROVED"
    assert receipt["payload"]["claims"] == claims
    assert verify_execution_admission(receipt, claims)[0] is True

    blocked = _approved_result()
    blocked["gates"]["gate_0"]["verdict"] = "BYPASSED"
    with pytest.raises(ValueError, match="gate_0"):
        issue_execution_admission(blocked, claims)


def test_admission_is_bound_to_task_lineage_amounts_and_destinations(monkeypatch):
    _configure_live(monkeypatch)
    claims = payments.build_payment_admission_claims("task-002", "b" * 64)
    receipt = issue_execution_admission(_approved_result(), claims)

    changed_amount = dict(claims)
    changed_amount["total_cents"] += 100
    assert verify_execution_admission(receipt, changed_amount)[0] is False

    changed_destination = dict(claims)
    changed_destination["destinations"] = dict(claims["destinations"])
    changed_destination["destinations"]["community"] = "acct_attacker123"
    assert verify_execution_admission(receipt, changed_destination)[0] is False


def test_expired_admission_is_rejected(monkeypatch):
    _configure_live(monkeypatch)
    claims = payments.build_payment_admission_claims("task-003", "c" * 64)
    receipt = issue_execution_admission(_approved_result(), claims, now_epoch=1000, ttl_seconds=30)
    valid, reason = verify_execution_admission(receipt, claims, now_epoch=1031)
    assert valid is False
    assert "expired" in reason


def test_live_payment_fails_closed_without_admission(monkeypatch):
    _configure_live(monkeypatch)
    called = []

    def must_not_transfer(*args, **kwargs):
        called.append((args, kwargs))
        raise AssertionError("Stripe transfer must not be attempted without admission")

    monkeypatch.setattr(payments, "_live_transfer", must_not_transfer)
    result = payments.process_manna_payment("task-004", "d" * 64)
    assert result.status == "failed"
    assert result.community_id is None
    assert not called


def test_live_payment_passes_receipt_to_each_transfer(monkeypatch):
    _configure_live(monkeypatch)
    task_id = "task-005"
    lineage_hash = "e" * 64
    claims = payments.build_payment_admission_claims(task_id, lineage_hash)
    receipt = issue_execution_admission(_approved_result(), claims)
    calls = []

    def fake_transfer(amount_cents, destination, task_id_arg, label, idempotency_key, admission_receipt=None):
        calls.append((amount_cents, destination, task_id_arg, label, idempotency_key, admission_receipt))
        return "tr_test_" + label

    monkeypatch.setattr(payments, "_live_transfer", fake_transfer)
    result = payments.process_manna_payment(task_id, lineage_hash, admission_receipt=receipt)
    assert result.status == "completed"
    assert len(calls) == 3
    assert all(call[2] == task_id and call[5] == receipt for call in calls)
    assert {call[3] for call in calls} == {"community", "crew", "architect"}


def test_direct_live_transfer_without_receipt_is_rejected_before_stripe(monkeypatch):
    _configure_live(monkeypatch)
    with pytest.raises(RuntimeError, match="admission"):
        payments._live_transfer(
            amount_cents=84,
            destination="acct_community123",
            task_id="task-006",
            label="community",
            idempotency_key=("f" * 64) + "_community",
            admission_receipt=None,
        )
