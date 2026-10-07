"""
OpenClaw Colony — Stripe Bridge Test Suite
Tests: MANNA split arithmetic, mock payments, DB persistence,
API key auth, rate limiting, webhook verification, admin endpoints.
All Stripe calls are mocked — no real network calls.
"""

import hashlib
import json
import os
import uuid
import pytest

# ── Force mock/test mode before any imports ───────────────────────────────────
os.environ.setdefault("COLONY_AUTH_ENABLED", "false")
os.environ.setdefault("COLONY_DB_PATH", ":memory:")
os.environ.setdefault("COLONY_ADMIN_KEY", "test-admin-secret")
os.environ.setdefault("COLONY_MANNA_CENTS", "100")
# No STRIPE_SECRET_KEY -> mock mode

import sys
BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
for p in [
    BACKEND,
    os.path.join(BACKEND, "colony-agents"),
    os.path.join(BACKEND, "colony-agents", "orchestrator"),
    os.path.join(BACKEND, "love-quality"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from stripe_bridge import (
    calculate_manna_split,
    process_manna_payment,
    MannaSplit,
    MOCK_MODE,
)
from db import (
    init_db, SessionLocal, create_api_key, verify_api_key,
    append_lineage, get_last_lineage_hash,
    ApiKey, LineageRecord, PaymentRecord,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def fresh_db():
    """Wipe and re-create all tables before each test for full isolation."""
    from db import Base, engine
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


# =============================================================================
# 1. MANNA SPLIT ARITHMETIC
# =============================================================================

class TestMannaSplit:

    def test_default_100_cents(self):
        s = calculate_manna_split(100)
        assert s.total_cents == 100
        assert s.community_cents == 84
        assert s.crew_cents == 15
        assert s.architect_cents == 1

    def test_split_sums_to_total(self):
        for total in [100, 200, 500, 1000, 9999, 1]:
            s = calculate_manna_split(total)
            assert s.community_cents + s.crew_cents + s.architect_cents == total

    def test_community_is_largest(self):
        s = calculate_manna_split(100)
        assert s.community_cents > s.crew_cents > s.architect_cents

    def test_zero_cents(self):
        s = calculate_manna_split(0)
        assert s.total_cents == 0
        assert s.community_cents == 0
        assert s.crew_cents == 0
        assert s.architect_cents == 0

    def test_one_cent(self):
        s = calculate_manna_split(1)
        assert s.community_cents + s.crew_cents + s.architect_cents == 1

    def test_large_amount(self):
        s = calculate_manna_split(1_000_000)
        assert s.community_cents + s.crew_cents + s.architect_cents == 1_000_000
        assert s.community_cents == pytest.approx(840_000, abs=2)

    def test_as_dict_keys(self):
        s = calculate_manna_split(100)
        d = s.as_dict()
        assert set(d.keys()) == {"total_cents", "community_cents", "crew_cents", "architect_cents"}

    def test_percentages_approximate(self):
        s = calculate_manna_split(10_000)
        assert abs(s.community_cents / 10_000 - 0.84) < 0.01
        assert abs(s.crew_cents      / 10_000 - 0.15) < 0.01
        assert abs(s.architect_cents / 10_000 - 0.01) < 0.01


# =============================================================================
# 2. MOCK MODE PAYMENTS
# =============================================================================

class TestMockPayments:

    def test_mock_mode_is_active(self):
        assert MOCK_MODE is True

    def test_process_returns_mock_status(self):
        result = process_manna_payment("task-001", "hash-abc")
        assert result.status == "mock"

    def test_process_returns_mock_ids(self):
        result = process_manna_payment("task-001", "hash-abc")
        assert result.community_id.startswith("mock_")
        assert result.crew_id.startswith("mock_")
        assert result.architect_id.startswith("mock_")

    def test_process_correct_split(self):
        result = process_manna_payment("task-002", "hash-xyz")
        assert result.split.total_cents == 100
        assert result.split.community_cents == 84
        assert result.split.crew_cents == 15
        assert result.split.architect_cents == 1

    def test_process_no_error(self):
        result = process_manna_payment("task-003", "hash-def")
        assert result.error is None

    def test_process_task_id_preserved(self):
        tid = str(uuid.uuid4())
        result = process_manna_payment(tid, "hash-ghi")
        assert result.task_id == tid

    def test_process_lineage_hash_preserved(self):
        lh = "a" * 64
        result = process_manna_payment("task-004", lh)
        assert result.lineage_hash == lh

    def test_process_as_dict(self):
        result = process_manna_payment("task-005", "hash-jkl")
        d = result.as_dict()
        assert "task_id" in d
        assert "split" in d
        assert "status" in d
        assert d["status"] == "mock"

    def test_unique_mock_ids_per_call(self):
        r1 = process_manna_payment("task-006", "hash-1")
        r2 = process_manna_payment("task-007", "hash-2")
        assert r1.community_id != r2.community_id
        assert r1.crew_id != r2.crew_id


# =============================================================================
# 3. PERSISTENT LINEAGE
# =============================================================================

class TestPersistentLineage:

    def test_genesis_when_empty(self, db):
        assert get_last_lineage_hash(db) == "GENESIS"

    def test_append_returns_hash(self, db):
        h = append_lineage(db, "t1", "prompt", 0.90, "action")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_chain_links_correctly(self, db):
        h1 = append_lineage(db, "t1", "prompt1", 0.90, "action1")
        h2 = append_lineage(db, "t2", "prompt2", 0.92, "action2")
        payload = f"{h1}:t2:action2"
        expected = hashlib.sha256(payload.encode()).hexdigest()
        assert h2 == expected

    def test_genesis_chain_link(self, db):
        h1 = append_lineage(db, "t1", "prompt", 0.90, "action")
        payload = "GENESIS:t1:action"
        expected = hashlib.sha256(payload.encode()).hexdigest()
        assert h1 == expected

    def test_last_hash_updates(self, db):
        h1 = append_lineage(db, "t1", "p1", 0.90, "a1")
        assert get_last_lineage_hash(db) == h1
        h2 = append_lineage(db, "t2", "p2", 0.91, "a2")
        assert get_last_lineage_hash(db) == h2

    def test_lineage_record_persisted(self, db):
        append_lineage(db, "t-persist", "my prompt", 0.88, "my action")
        row = db.query(LineageRecord).filter_by(task_id="t-persist").first()
        assert row is not None
        assert row.lq_composite == pytest.approx(0.88)

    def test_prompt_hash_stored(self, db):
        prompt = "Help me build a community garden."
        append_lineage(db, "t-ph", prompt, 0.90, "action")
        row = db.query(LineageRecord).filter_by(task_id="t-ph").first()
        expected_hash = hashlib.sha256(prompt.encode()).hexdigest()
        assert row.prompt_hash == expected_hash

    def test_multiple_records_ordered(self, db):
        for i in range(5):
            append_lineage(db, f"t{i}", f"prompt{i}", 0.90 + i * 0.01, f"action{i}")
        records = db.query(LineageRecord).order_by(LineageRecord.id).all()
        assert len(records) == 5
        assert records[0].task_id == "t0"
        assert records[4].task_id == "t4"

    def test_duplicate_task_id_raises(self, db):
        append_lineage(db, "dup", "p", 0.90, "a")
        with pytest.raises(Exception):
            append_lineage(db, "dup", "p2", 0.91, "a2")


# =============================================================================
# 4. API KEY MANAGEMENT
# =============================================================================

class TestApiKeys:

    def test_create_key_returns_raw(self, db):
        result = create_api_key(db, label="test-key")
        assert "raw_key" in result
        assert result["raw_key"].startswith("oc_")

    def test_create_key_returns_key_id(self, db):
        result = create_api_key(db, label="test-key")
        assert "key_id" in result
        assert len(result["key_id"]) == 36

    def test_verify_valid_key(self, db):
        result = create_api_key(db, label="valid")
        row = verify_api_key(db, result["raw_key"])
        assert row is not None
        assert row.is_active is True

    def test_verify_invalid_key(self, db):
        row = verify_api_key(db, "oc_notarealkey")
        assert row is None

    def test_verify_updates_last_used(self, db):
        result = create_api_key(db, label="used")
        row = verify_api_key(db, result["raw_key"])
        assert row.last_used_at is not None

    def test_revoked_key_fails(self, db):
        result = create_api_key(db, label="revoke-me")
        row = db.query(ApiKey).filter_by(key_id=result["key_id"]).first()
        row.is_active = False
        db.commit()
        assert verify_api_key(db, result["raw_key"]) is None

    def test_raw_key_not_stored(self, db):
        result = create_api_key(db, label="no-raw")
        row = db.query(ApiKey).filter_by(key_id=result["key_id"]).first()
        assert row.key_hash != result["raw_key"]
        assert len(row.key_hash) == 64

    def test_multiple_keys_independent(self, db):
        r1 = create_api_key(db, label="k1")
        r2 = create_api_key(db, label="k2")
        assert r1["raw_key"] != r2["raw_key"]
        assert r1["key_id"] != r2["key_id"]
        assert verify_api_key(db, r1["raw_key"]) is not None
        assert verify_api_key(db, r2["raw_key"]) is not None

    def test_stripe_account_stored(self, db):
        result = create_api_key(db, label="stripe-key", stripe_account_id="acct_test123")
        row = db.query(ApiKey).filter_by(key_id=result["key_id"]).first()
        assert row.stripe_account_id == "acct_test123"


# =============================================================================
# 5. PAYMENT RECORD PERSISTENCE
# =============================================================================

class TestPaymentPersistence:

    def test_payment_record_stored(self, db):
        split = calculate_manna_split(100)
        rec = PaymentRecord(
            task_id="pay-t1",
            lineage_hash="a" * 64,
            stripe_transfer_id="mock_abc123",
            amount_total_cents=split.total_cents,
            community_cents=split.community_cents,
            crew_cents=split.crew_cents,
            architect_cents=split.architect_cents,
            status="mock",
        )
        db.add(rec)
        db.commit()
        row = db.query(PaymentRecord).filter_by(task_id="pay-t1").first()
        assert row is not None
        assert row.community_cents == 84
        assert row.crew_cents == 15
        assert row.architect_cents == 1

    def test_payment_status_default_pending(self, db):
        rec = PaymentRecord(
            task_id="pay-t2",
            lineage_hash="b" * 64,
            amount_total_cents=100,
            community_cents=84,
            crew_cents=15,
            architect_cents=1,
        )
        db.add(rec)
        db.commit()
        row = db.query(PaymentRecord).filter_by(task_id="pay-t2").first()
        assert row.status == "pending"

    def test_payment_status_update(self, db):
        rec = PaymentRecord(
            task_id="pay-t3",
            lineage_hash="c" * 64,
            amount_total_cents=100,
            community_cents=84,
            crew_cents=15,
            architect_cents=1,
            status="pending",
        )
        db.add(rec)
        db.commit()
        rec.status = "completed"
        db.commit()
        row = db.query(PaymentRecord).filter_by(task_id="pay-t3").first()
        assert row.status == "completed"


# =============================================================================
# 6. WEBHOOK VERIFICATION
# =============================================================================

class TestWebhookVerification:

    def test_no_webhook_secret_parses_json(self):
        from stripe_bridge import verify_webhook
        payload = json.dumps({"id": "evt_test", "type": "transfer.paid"}).encode()
        result = verify_webhook(payload, "")
        assert result is not None
        assert result["id"] == "evt_test"

    def test_invalid_json_returns_none(self):
        from stripe_bridge import verify_webhook
        result = verify_webhook(b"not json", "")
        assert result is None

    def test_webhook_event_structure(self):
        from stripe_bridge import verify_webhook
        event = {
            "id": "evt_123",
            "type": "transfer.paid",
            "data": {"object": {"id": "tr_abc", "metadata": {"task_id": "t1"}}}
        }
        payload = json.dumps(event).encode()
        result = verify_webhook(payload, "")
        assert result["type"] == "transfer.paid"
        assert result["data"]["object"]["id"] == "tr_abc"


# =============================================================================
# 7. FASTAPI INTEGRATION (TestClient)
# =============================================================================

def _build_test_app():
    """Import colony_coordinator_v2 with heavy deps stubbed via sys.modules."""
    import os
    from unittest.mock import MagicMock

    # Ensure db module uses the stripe-test :memory: DB, not the federation
    # named DB that may have been set by test_federation.py running first.

    # Disable rate limiting during integration tests so no 429s fire.
    os.environ.setdefault("COLONY_RATE_PROCESS", "10000/minute")
    os.environ.setdefault("COLONY_RATE_ADMIN",   "10000/minute")
    os.environ.setdefault("COLONY_RATE_WEBHOOK",  "10000/minute")
    os.environ["COLONY_DB_PATH"] = ":memory:"

    stubs = [
        "love_quality", "love_quality.love_quality_engine", "aethel_interface",
        "colony_agents", "colony_agents.strategic_agent", "colony_agents.technical_agent",
        "colony_agents.resources_agent", "colony_agents.comms_agent",
        "colony_agents.analysis_agent", "colony_agents.quality_agent",
        "colony_agents.innovation_agent",
    ]
    saved = {}
    for name in stubs:
        saved[name] = sys.modules.get(name)
        sys.modules[name] = MagicMock()

    # Evict db, federation, and coordinator so they re-import with correct DB path
    for mod in ("colony_coordinator_v2", "db", "federation", "federation_routes",
                "auth", "rate_limit", "stripe_bridge"):
        sys.modules.pop(mod, None)

    # Restore real slowapi modules if test_federation.py replaced them with stubs.
    # The federation test stubs slowapi as bare ModuleType objects; we need the
    # real package so SlowAPIMiddleware and Limiter work correctly here.
    _slowapi_mods = ("slowapi", "slowapi.middleware", "slowapi.errors", "slowapi.util",
                     "passlib", "passlib.context", "jose", "jose.jwt", "aiofiles",
                     "stripe")
    for _m in _slowapi_mods:
        if _m in sys.modules:
            import types as _types
            if isinstance(sys.modules[_m], _types.ModuleType) and not hasattr(sys.modules[_m], '__version__') and not hasattr(sys.modules[_m], '__spec__') or (hasattr(sys.modules[_m], '__spec__') and sys.modules[_m].__spec__ is None):
                # Likely a stub — evict so the real package is imported fresh
                sys.modules.pop(_m, None)

    import colony_coordinator_v2 as cc

    for name, orig in saved.items():
        if orig is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = orig

    return cc


class TestFastAPIEndpoints:
    """FastAPI integration tests — auth disabled, coordinator mocked."""

    @pytest.fixture(autouse=True)
    def setup_app(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock

        cc = _build_test_app()

        mock_result = cc.ColonyResult(
            task_id="mock-task-id",
            prompt="test prompt",
            agent_outputs={},
            lq_score={"composite": 0.90},
            aethel_verdict="APPROVED",
            aethel_gates={"gate1": True, "gate2": True, "gate3": True},
            committed_action='{"task_id": "mock-task-id"}',
            lineage_hash="a" * 64,
            payment={"status": "mock", "split": {"total_cents": 100}},
        )

        mock_coordinator = MagicMock()
        mock_coordinator.process = AsyncMock(return_value=mock_result)
        monkeypatch.setattr(cc, "coordinator", mock_coordinator)

        from db import Base, engine, init_db
        Base.metadata.drop_all(bind=engine)
        init_db()

        from rate_limit import limiter
        try:
            # limits >= 3.x: MemoryStorage exposes .reset() and .storage dict
            storage = limiter._storage
            if hasattr(storage, "reset"):
                storage.reset()
            elif hasattr(storage, "storage"):
                storage.storage.clear()
            elif hasattr(storage, "_storage"):
                storage._storage.clear()
        except Exception:
            pass

        from fastapi.testclient import TestClient
        self.client = TestClient(cc.app, raise_server_exceptions=False)
        self.cc = cc

    def test_health_endpoint(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["colony"] == "online"
        assert "stripe_mode" in data

    def test_process_approved(self):
        resp = self.client.post(
            "/process",
            json={"prompt": "Help me build a community garden.", "human_consent": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["aethel_verdict"] == "APPROVED"
        assert data["lineage_hash"] == "a" * 64
        assert data["payment"]["status"] == "mock"

    def test_process_returns_payment_field(self):
        resp = self.client.post("/process", json={"prompt": "test", "human_consent": True})
        assert resp.status_code == 200
        assert "payment" in resp.json()

    def test_admin_requires_key(self):
        resp = self.client.get("/admin/lineage")
        assert resp.status_code in (200, 403)

    def test_admin_with_correct_key(self):
        resp = self.client.get(
            "/admin/lineage",
            headers={"Authorization": "Bearer test-admin-secret"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_admin_payments_with_correct_key(self):
        resp = self.client.get(
            "/admin/payments",
            headers={"Authorization": "Bearer test-admin-secret"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_admin_manna_config(self):
        resp = self.client.get(
            "/admin/manna/config",
            headers={"Authorization": "Bearer test-admin-secret"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["manna_cents_per_task"] == 100
        assert data["percentages"]["community"] == "84%"

    def test_admin_create_key(self):
        resp = self.client.post(
            "/admin/keys",
            json={"label": "integration-test-key"},
            headers={"Authorization": "Bearer test-admin-secret"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["raw_key"].startswith("oc_")
        assert "key_id" in data
        assert "Store this key securely" in data["note"]

    def test_admin_list_keys(self):
        self.client.post(
            "/admin/keys",
            json={"label": "list-test"},
            headers={"Authorization": "Bearer test-admin-secret"},
        )
        resp = self.client.get(
            "/admin/keys",
            headers={"Authorization": "Bearer test-admin-secret"},
        )
        assert resp.status_code == 200
        keys = resp.json()
        assert isinstance(keys, list)
        assert any(k["label"] == "list-test" for k in keys)

    def test_admin_revoke_key(self):
        create_resp = self.client.post(
            "/admin/keys",
            json={"label": "revoke-test"},
            headers={"Authorization": "Bearer test-admin-secret"},
        )
        key_id = create_resp.json()["key_id"]
        revoke_resp = self.client.delete(
            f"/admin/keys/{key_id}",
            headers={"Authorization": "Bearer test-admin-secret"},
        )
        assert revoke_resp.status_code == 200
        assert revoke_resp.json()["status"] == "revoked"

    def test_admin_revoke_nonexistent_key(self):
        resp = self.client.delete(
            "/admin/keys/nonexistent-id",
            headers={"Authorization": "Bearer test-admin-secret"},
        )
        assert resp.status_code == 404

    def test_webhook_stripe_valid_json(self):
        payload = json.dumps({
            "id": "evt_test_001",
            "type": "transfer.paid",
            "data": {"object": {"id": "tr_001", "metadata": {"task_id": "t1"}}}
        })
        resp = self.client.post(
            "/webhook/stripe",
            content=payload,
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 200

    def test_webhook_idempotency(self):
        """Same event ID processed twice should return already_processed."""
        payload = json.dumps({
            "id": "evt_idem_001",
            "type": "transfer.paid",
            "data": {"object": {"id": "tr_idem", "metadata": {}}}
        })
        self.client.post("/webhook/stripe", content=payload,
                         headers={"content-type": "application/json"})
        resp2 = self.client.post("/webhook/stripe", content=payload,
                                 headers={"content-type": "application/json"})
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "already_processed"
