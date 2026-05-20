"""
OpenClaw Colony — Federation Layer Tests
Tests for node registry, lineage gossip, cross-node proposals, and voting.

Isolation strategy:
  - Uses a SEPARATE named in-memory SQLite DB ("fed_test_db") so it never
    shares the cache with test_stripe_bridge.py's ":memory:" shared DB.
  - All db/federation modules are imported AFTER setting COLONY_DB_PATH,
    ensuring the engine points at the right database.
"""

import sys
import types
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

# ── Stub heavy dependencies before any colony imports ─────────────────────────

def _make_stub(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m

for _mod in [
    "stripe", "slowapi", "slowapi.middleware", "slowapi.errors", "slowapi.util",
    "passlib", "passlib.context",
    "jose", "jose.jwt",
    "aiofiles",
    "love_quality",
    "aethel_interface",
    "colony_agents",
    "colony_agents.strategic_agent",
    "colony_agents.technical_agent",
    "colony_agents.resources_agent",
    "colony_agents.comms_agent",
    "colony_agents.analysis_agent",
    "colony_agents.quality_agent",
    "colony_agents.innovation_agent",
]:
    if _mod not in sys.modules:
        _make_stub(_mod)

# Stub love_quality engine
import love_quality as _lq_pkg
_lq_engine_mod = types.ModuleType("love_quality.love_quality_engine")

class _FakeDim:
    def __init__(self):
        self.name = "test"; self.raw_score = 0.9; self.weighted_score = 0.9

class _FakeLQ:
    composite = 0.92
    passed = True
    rejection_reason = ""
    dimensions = [_FakeDim()]

class _FakeLQEngine:
    def score(self, *a, **kw): return _FakeLQ()

_lq_engine_mod.LoveQualityEngine = _FakeLQEngine
_lq_engine_mod.LQ_THRESHOLD = 0.85
_lq_engine_mod.LQScore = _FakeLQ
sys.modules["love_quality.love_quality_engine"] = _lq_engine_mod
_lq_pkg.love_quality_engine = _lq_engine_mod

# Stub aethel — deferred to fixture so module-level mutation doesn't contaminate
# other test modules collected in the same pytest session.
import aethel_interface as _ai
_REAL_AethelInterface = _ai.AethelInterface  # saved for restore

# Stub slowapi
import slowapi as _sa
_sa.Limiter = MagicMock(return_value=MagicMock(
    limit=lambda *a, **kw: (lambda f: f),
))
import slowapi.middleware as _sam; _sam.SlowAPIMiddleware = MagicMock()
import slowapi.errors as _sae; _sae.RateLimitExceeded = Exception
import slowapi.util as _sau; _sau.get_remote_address = lambda r: "127.0.0.1"

# Stub passlib
import passlib as _pl; import passlib.context as _plc
_plc.CryptContext = MagicMock(return_value=MagicMock(
    hash=lambda s: "hashed_" + s,
    verify=lambda plain, hashed: hashed == "hashed_" + plain,
))

# ── Set env BEFORE importing db/federation ────────────────────────────────────
import os

# Use a uniquely named in-memory DB so federation tests are fully isolated
# from the shared ":memory:" cache used by test_stripe_bridge.py
os.environ["COLONY_DB_PATH"]      = "file:fed_test_db?mode=memory&cache=shared&uri=true"
os.environ["COLONY_AUTH_ENABLED"] = "false"
os.environ["COLONY_ADMIN_KEY"]    = "test-admin-secret"
os.environ["COLONY_NODE_ID"]      = "node-001-test"
os.environ["COLONY_NODE_URL"]     = "http://localhost:8000"
os.environ["COLONY_PEERS"]        = ""
os.environ["STRIPE_SECRET_KEY"]   = ""

# ── Import colony modules (engine created with correct DB path) ───────────────
from db import init_db, SessionLocal, LineageRecord, append_lineage
from federation import (
    init_federation_tables,
    FederatedNode, CrossNodeProposal, FederationVote,
    register_peer, get_active_peers, mark_peer_inactive,
    record_vote, create_proposal,
    NODE_ID,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def _stub_and_restore_aethel():
    """Stub AethelInterface for federation tests, restore after module completes."""
    _ai.AethelInterface = MagicMock(return_value=MagicMock(
        validate=MagicMock(return_value={
            "verdict": "APPROVED",
            "gates": {"sovereignty": True, "lq_threshold": True, "extraction_scan": True},
        })
    ))
    yield
    _ai.AethelInterface = _REAL_AethelInterface


@pytest.fixture(autouse=True)
def fresh_db():
    """Reinitialise DB tables and clear data before each test."""
    init_db()
    init_federation_tables()
    db = SessionLocal()
    try:
        db.query(FederationVote).delete()
        db.query(CrossNodeProposal).delete()
        db.query(FederatedNode).delete()
        db.query(LineageRecord).delete()
        db.commit()
    finally:
        db.close()
    yield


# ── TestNodeRegistry ──────────────────────────────────────────────────────────

class TestNodeRegistry:

    def test_register_new_peer(self):
        db = SessionLocal()
        try:
            node = register_peer("node-002", "http://node002.test", db)
            assert node.node_id  == "node-002"
            assert node.base_url == "http://node002.test"
            assert node.active   is True
        finally:
            db.close()

    def test_register_peer_upsert(self):
        db = SessionLocal()
        try:
            register_peer("node-002", "http://old.url", db)
            register_peer("node-002", "http://new.url", db)
            count = db.query(FederatedNode).filter_by(node_id="node-002").count()
            assert count == 1
            node = db.query(FederatedNode).filter_by(node_id="node-002").first()
            assert node.base_url == "http://new.url"
        finally:
            db.close()

    def test_get_active_peers(self):
        db = SessionLocal()
        try:
            register_peer("node-002", "http://node002.test", db)
            register_peer("node-003", "http://node003.test", db)
            peers = get_active_peers(db)
            assert len(peers) == 2
        finally:
            db.close()

    def test_mark_peer_inactive(self):
        db = SessionLocal()
        try:
            register_peer("node-002", "http://node002.test", db)
            mark_peer_inactive("node-002", db)
            peers = get_active_peers(db)
            assert len(peers) == 0
        finally:
            db.close()

    def test_mark_nonexistent_peer_inactive_is_safe(self):
        db = SessionLocal()
        try:
            mark_peer_inactive("ghost-node", db)
        finally:
            db.close()

    def test_multiple_peers_independent(self):
        db = SessionLocal()
        try:
            for i in range(5):
                register_peer(f"node-{i:03d}", f"http://node{i}.test", db)
            assert db.query(FederatedNode).count() == 5
        finally:
            db.close()


# ── TestCrossNodeProposals ────────────────────────────────────────────────────

class TestCrossNodeProposals:

    def test_create_proposal(self):
        db = SessionLocal()
        try:
            p = create_proposal("Allocate 10 units of water to sector 3", "abc123", db)
            assert p.proposal_id is not None
            assert p.status      == "pending"
            assert p.origin_node == NODE_ID
            assert p.votes_for   == 0
        finally:
            db.close()

    def test_single_approve_vote(self):
        db = SessionLocal()
        try:
            p = create_proposal("Test proposal", "hash001", db)
            register_peer("node-002", "http://node002.test", db)
            updated = record_vote(p.proposal_id, "node-002", "approve", "0.91", db)
            assert updated.votes_for == 1
        finally:
            db.close()

    def test_quorum_approval(self):
        db = SessionLocal()
        try:
            register_peer("node-002", "http://node002.test", db)
            register_peer("node-003", "http://node003.test", db)
            p = create_proposal("Quorum test", "hash002", db)
            record_vote(p.proposal_id, "node-002", "approve", "0.90", db)
            updated = record_vote(p.proposal_id, "node-003", "approve", "0.88", db)
            assert updated.status        == "approved"
            assert updated.quorum_reached is True
        finally:
            db.close()

    def test_quorum_block(self):
        db = SessionLocal()
        try:
            register_peer("node-002", "http://node002.test", db)
            register_peer("node-003", "http://node003.test", db)
            p = create_proposal("Block test", "hash003", db)
            record_vote(p.proposal_id, "node-002", "block", "0.40", db)
            updated = record_vote(p.proposal_id, "node-003", "block", "0.35", db)
            assert updated.status == "blocked"
        finally:
            db.close()

    def test_vote_idempotency(self):
        db = SessionLocal()
        try:
            register_peer("node-002", "http://node002.test", db)
            p = create_proposal("Idempotency test", "hash004", db)
            record_vote(p.proposal_id, "node-002", "approve", "0.90", db)
            record_vote(p.proposal_id, "node-002", "approve", "0.90", db)
            updated = db.query(CrossNodeProposal).filter_by(
                proposal_id=p.proposal_id
            ).first()
            assert updated.votes_for == 1
        finally:
            db.close()

    def test_resolved_proposal_ignores_new_votes(self):
        db = SessionLocal()
        try:
            register_peer("node-002", "http://node002.test", db)
            register_peer("node-003", "http://node003.test", db)
            p = create_proposal("Already resolved", "hash005", db)
            record_vote(p.proposal_id, "node-002", "approve", "0.90", db)
            record_vote(p.proposal_id, "node-003", "approve", "0.88", db)
            register_peer("node-004", "http://node004.test", db)
            updated = record_vote(p.proposal_id, "node-004", "block", "0.20", db)
            assert updated.status == "approved"
        finally:
            db.close()

    def test_proposal_with_no_peers(self):
        db = SessionLocal()
        try:
            p = create_proposal("No peers", "hash006", db)
            assert p.status == "pending"
        finally:
            db.close()


# ── TestLineageGossip ─────────────────────────────────────────────────────────

class TestLineageGossip:

    def test_lineage_records_visible_to_federation(self):
        db = SessionLocal()
        try:
            h = append_lineage(db, "task-fed-001", "test prompt", 0.91, "{}")
            records = db.query(LineageRecord).all()
            assert len(records) == 1
            assert records[0].lineage_hash == h
        finally:
            db.close()

    def test_multiple_lineage_records_chain(self):
        db = SessionLocal()
        try:
            h1 = append_lineage(db, "task-fed-001", "prompt 1", 0.91, "{}")
            h2 = append_lineage(db, "task-fed-002", "prompt 2", 0.92, "{}")
            h3 = append_lineage(db, "task-fed-003", "prompt 3", 0.93, "{}")
            records = db.query(LineageRecord).order_by(LineageRecord.id).all()
            assert records[1].prev_hash == h1
            assert records[2].prev_hash == h2
            assert h1 != h2 != h3
        finally:
            db.close()

    def test_lineage_since_hash_slicing(self):
        db = SessionLocal()
        try:
            h1 = append_lineage(db, "task-fed-001", "prompt 1", 0.91, "{}")
            h2 = append_lineage(db, "task-fed-002", "prompt 2", 0.92, "{}")
            h3 = append_lineage(db, "task-fed-003", "prompt 3", 0.93, "{}")
            records = db.query(LineageRecord).order_by(LineageRecord.id).all()
            start_idx = 0
            for i, r in enumerate(records):
                if r.lineage_hash == h1:
                    start_idx = i + 1
                    break
            sliced = records[start_idx:]
            assert len(sliced) == 2
            assert sliced[0].lineage_hash == h2
            assert sliced[1].lineage_hash == h3
        finally:
            db.close()


# ── TestFederationAPI ─────────────────────────────────────────────────────────

class TestFederationAPI:

    def _build_app(self):
        """Build a test FastAPI app with federation routes, using fed_test_db."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import federation_routes as fr
        test_app = FastAPI()
        test_app.include_router(fr.router)
        return TestClient(test_app)

    def _auth_headers(self):
        return {"Authorization": "Bearer test-admin-secret"}

    def test_announce_endpoint(self):
        client = self._build_app()
        r = client.post(
            "/federation/announce",
            json={"node_id": "node-002", "node_url": "http://node002.test"},
            headers=self._auth_headers(),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"]  == "registered"
        assert data["node_id"] == "node-002"

    def test_lineage_tip_endpoint(self):
        client = self._build_app()
        r = client.post(
            "/federation/lineage-tip",
            json={
                "node_id":   "node-002",
                "node_url":  "http://node002.test",
                "tip_hash":  "abc123",
                "tip_index": 5,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers=self._auth_headers(),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "tip_received"

    def test_list_nodes_endpoint(self):
        client = self._build_app()
        client.post(
            "/federation/announce",
            json={"node_id": "node-002", "node_url": "http://node002.test"},
            headers=self._auth_headers(),
        )
        r = client.get("/federation/nodes", headers=self._auth_headers())
        assert r.status_code == 200
        data = r.json()
        assert "peers" in data
        assert any(p["node_id"] == "node-002" for p in data["peers"])

    def test_serve_lineage_endpoint(self):
        client = self._build_app()
        r = client.get("/federation/lineage", headers=self._auth_headers())
        assert r.status_code == 200
        data = r.json()
        assert "records" in data
        assert "node_id" in data

    def test_federation_status_endpoint(self):
        client = self._build_app()
        r = client.get("/federation/status", headers=self._auth_headers())
        assert r.status_code == 200
        data = r.json()
        assert "node_id"   in data
        assert "peers"     in data
        assert "lineage"   in data
        assert "proposals" in data

    def test_proposal_receive_and_vote(self):
        client = self._build_app()
        proposal_id = str(uuid.uuid4())
        r = client.post(
            "/federation/proposals",
            json={
                "proposal_id": proposal_id,
                "origin_node": "node-002",
                "prompt_hash": "deadbeef",
                "description": "Allocate water to sector 3",
                "created_at":  datetime.now(timezone.utc).isoformat(),
            },
            headers=self._auth_headers(),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["proposal_id"] == proposal_id
        assert data["our_vote"] in ("approve", "block")

    def test_proposal_idempotency(self):
        client = self._build_app()
        proposal_id = str(uuid.uuid4())
        payload = {
            "proposal_id": proposal_id,
            "origin_node": "node-002",
            "prompt_hash": "deadbeef",
            "description": "Idempotency check",
            "created_at":  datetime.now(timezone.utc).isoformat(),
        }
        client.post("/federation/proposals", json=payload, headers=self._auth_headers())
        r2 = client.post("/federation/proposals", json=payload, headers=self._auth_headers())
        assert r2.status_code == 200
        assert r2.json()["status"] == "already_known"

    def test_vote_endpoint(self):
        client = self._build_app()
        proposal_id = str(uuid.uuid4())
        client.post(
            "/federation/proposals",
            json={
                "proposal_id": proposal_id,
                "origin_node": "node-002",
                "prompt_hash": "deadbeef",
                "description": "Vote endpoint test",
                "created_at":  datetime.now(timezone.utc).isoformat(),
            },
            headers=self._auth_headers(),
        )
        r = client.post(
            "/federation/votes",
            json={
                "proposal_id": proposal_id,
                "voter_node":  "node-003",
                "vote":        "approve",
                "lq_score":    "0.88",
            },
            headers=self._auth_headers(),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "vote_recorded"

    def test_vote_invalid_value(self):
        client = self._build_app()
        proposal_id = str(uuid.uuid4())
        client.post(
            "/federation/proposals",
            json={
                "proposal_id": proposal_id,
                "origin_node": "node-002",
                "prompt_hash": "deadbeef",
                "description": "Invalid vote test",
                "created_at":  datetime.now(timezone.utc).isoformat(),
            },
            headers=self._auth_headers(),
        )
        r = client.post(
            "/federation/votes",
            json={
                "proposal_id": proposal_id,
                "voter_node":  "node-003",
                "vote":        "maybe",
                "lq_score":    "0.88",
            },
            headers=self._auth_headers(),
        )
        assert r.status_code == 400

    def test_get_proposal_status(self):
        client = self._build_app()
        proposal_id = str(uuid.uuid4())
        client.post(
            "/federation/proposals",
            json={
                "proposal_id": proposal_id,
                "origin_node": "node-002",
                "prompt_hash": "deadbeef",
                "description": "Status check test",
                "created_at":  datetime.now(timezone.utc).isoformat(),
            },
            headers=self._auth_headers(),
        )
        r = client.get(
            f"/federation/proposals/{proposal_id}",
            headers=self._auth_headers(),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["proposal_id"] == proposal_id
        assert "votes" in data

    def test_get_nonexistent_proposal(self):
        client = self._build_app()
        r = client.get(
            f"/federation/proposals/{uuid.uuid4()}",
            headers=self._auth_headers(),
        )
        assert r.status_code == 404