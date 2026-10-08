"""Platform boundary tests.

These tests verify the new pieces that turn OpenClaw Colony into the AETHEL
Operations Platform without changing the existing safety verdict behavior.
"""

import hashlib
import os
import sys
from datetime import datetime, timezone

import pytest

BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
for path in [BACKEND, os.path.join(BACKEND, "colony-agents"), os.path.join(BACKEND, "love-quality")]:
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture(autouse=True)
def fresh_db():
    from db import Base, engine
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


def test_task_record_persists_complete_request():
    from db import SessionLocal, TaskRecord

    db = SessionLocal()
    try:
        task_id = "platform-task-001"
        prompt = "Test the platform boundary."
        db.add(
            TaskRecord(
                task_id=task_id,
                prompt_hash=hashlib.sha256(prompt.encode()).hexdigest(),
                action_type="proposal",
                human_consent=True,
                lq_composite=0.91,
                status="APPROVED",
                blocked_at_gate=None,
                reason=None,
                lineage_hash="a" * 64,
                submitted_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        row = db.query(TaskRecord).filter_by(task_id=task_id).one()
        assert row.status == "APPROVED"
        assert row.lq_composite == pytest.approx(0.91)
        assert row.lineage_hash == "a" * 64
    finally:
        db.close()


def test_task_record_can_store_blocked_request():
    from db import SessionLocal, TaskRecord

    db = SessionLocal()
    try:
        db.add(
            TaskRecord(
                task_id="platform-task-blocked",
                prompt_hash="b" * 64,
                action_type="proposal",
                human_consent=False,
                lq_composite=0.91,
                status="BLOCKED",
                blocked_at_gate=1,
                reason="human consent required",
                lineage_hash=None,
                submitted_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        row = db.query(TaskRecord).filter_by(task_id="platform-task-blocked").one()
        assert row.status == "BLOCKED"
        assert row.blocked_at_gate == 1
        assert row.lineage_hash is None
    finally:
        db.close()


def test_integration_registry_separates_connected_from_planned():
    from integration_registry import list_integrations

    items = {item["key"]: item for item in list_integrations()}
    assert items["colony-core"]["status"] == "connected"
    assert items["safety-kernel"]["status"] == "connected"
    assert items["sports-math"]["status"] == "planned"
    assert items["project-mono"]["status"] == "planned"
    assert items["undermoon"]["status"] == "planned"
    assert items["aethel-grid"]["status"] == "planned"


def test_integration_registry_reports_external_endpoint_configuration(monkeypatch):
    from integration_registry import list_integrations

    monkeypatch.setenv("AETHEL_SPORTS_MATH_URL", "http://sports-math.local")
    items = {item["key"]: item for item in list_integrations()}
    assert items["sports-math"]["configured"] is True
    assert items["sports-math"]["endpoint"] == "http://sports-math.local"
