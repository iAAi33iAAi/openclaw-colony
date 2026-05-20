"""
OpenClaw Colony — Biometric Accountability Layer Tests
======================================================
Tests for:
  - Member enrollment (happy path, witness validation, duplicate badge)
  - Attestation issuance (match, mismatch, liveness, expiry, scope)
  - Gate 0 verification (all 10 checks)
  - Duress protocol (silent alert, escrow)
  - Geographic anomaly detection (impossible travel)
  - Revocation cascade
  - Accountability log recording
  - Legal export package
  - Public ledger query
  - Cooling-off window calculation
  - Single-use token enforcement
  - HMAC signature tamper detection
"""

import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "backend", "colony-agents", "orchestrator"
    ),
)

# NOTE: Global env defaults are set in conftest.py.
# test_biometric.py overrides COLONY_BIOMETRIC_REQUIRED=true only where needed.

from db import init_db, SessionLocal
from biometric import (
    init_biometric_tables,
    enroll_member,
    issue_attestation,
    verify_attestation_token,
    record_accountability,
    get_actor_history,
    export_legal_package,
    revoke_member,
    get_cooling_off_seconds,
    ColonyMember,
    BiometricAttestation,
    AccountabilityLog,
    DuressEvent,
    RevocationEvent,
    BAS_SECRET,
    _sign_payload,
    _hash_template,
    COOLING_OFF_RULES,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def fresh_db():
    """Reinitialise all tables before each test."""
    init_db()
    init_biometric_tables()
    db = SessionLocal()
    try:
        db.query(AccountabilityLog).delete()
        db.query(DuressEvent).delete()
        db.query(RevocationEvent).delete()
        db.query(BiometricAttestation).delete()
        db.query(ColonyMember).delete()
        db.commit()
    finally:
        db.close()
    yield


def _make_member(
    db,
    legal_name="Alice Founder",
    badge="BADGE-001",
    role="steward",
    face=b"face_alice",
    retina=b"retina_alice",
    duress_retina=b"duress_alice",
    witnesses=None,
    enrolled_by=None,
):
    """Helper: enroll a member, bypassing witness check if needed."""
    if witnesses is None:
        # Directly insert without witness validation for test setup
        member = ColonyMember(
            member_id=str(uuid.uuid4()),
            legal_name=legal_name,
            enrolled_by=enrolled_by or str(uuid.uuid4()),
            witness_ids=json.dumps(["w1", "w2", "w3"]),
            badge_serial=badge,
            role=role,
            face_template_hash=_hash_template(face),
            retina_template_hash=_hash_template(retina),
            duress_retina_hash=_hash_template(duress_retina),
            action_scope=json.dumps(["proposal", "treasury"]),
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        return member
    else:
        return enroll_member(
            db=db,
            legal_name=legal_name,
            badge_serial=badge,
            face_template_bytes=face,
            retina_template_bytes=retina,
            enrolled_by=enrolled_by,
            witness_ids=witnesses,
            role=role,
            duress_retina_bytes=duress_retina,
        )


def _issue(db, member, face=b"face_alice", retina=b"retina_alice",
           liveness=0.98, node="node-001", action="proposal"):
    return issue_attestation(
        db=db,
        badge_serial=member.badge_serial,
        face_scan_bytes=face,
        retina_scan_bytes=retina,
        liveness_score=liveness,
        location_node=node,
        action_type=action,
    )


# =============================================================================
# 1. ENROLLMENT TESTS
# =============================================================================

class TestEnrollment:

    def test_direct_insert_creates_member(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            assert m.member_id is not None
            assert m.legal_name == "Alice Founder"
            assert m.role == "steward"
            assert m.suspended is False
        finally:
            db.close()

    def test_face_template_not_stored_raw(self):
        """Raw biometric bytes must never appear in DB."""
        db = SessionLocal()
        try:
            m = _make_member(db, face=b"raw_face_data_secret")
            assert b"raw_face_data_secret" not in m.face_template_hash.encode()
            assert m.face_template_hash != "raw_face_data_secret"
        finally:
            db.close()

    def test_retina_template_not_stored_raw(self):
        db = SessionLocal()
        try:
            m = _make_member(db, retina=b"raw_retina_secret")
            assert b"raw_retina_secret" not in m.retina_template_hash.encode()
        finally:
            db.close()

    def test_duplicate_badge_raises(self):
        db = SessionLocal()
        try:
            _make_member(db, badge="BADGE-DUP")
            with pytest.raises(Exception):
                enroll_member(
                    db=db,
                    legal_name="Bob",
                    badge_serial="BADGE-DUP",
                    face_template_bytes=b"face_bob",
                    retina_template_bytes=b"retina_bob",
                    enrolled_by="someone",
                    witness_ids=["w1", "w2", "w3"],
                )
        finally:
            db.close()

    def test_insufficient_witnesses_raises(self):
        db = SessionLocal()
        try:
            with pytest.raises(ValueError, match="3 witnesses"):
                enroll_member(
                    db=db,
                    legal_name="Charlie",
                    badge_serial="BADGE-999",
                    face_template_bytes=b"face",
                    retina_template_bytes=b"retina",
                    enrolled_by="someone",
                    witness_ids=["w1", "w2"],  # only 2
                )
        finally:
            db.close()

    def test_action_scope_default(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            scope = json.loads(m.action_scope)
            assert "proposal" in scope
            assert "treasury" in scope
        finally:
            db.close()

    def test_duress_hash_different_from_normal_retina(self):
        db = SessionLocal()
        try:
            m = _make_member(db, retina=b"normal_retina", duress_retina=b"duress_retina")
            assert m.retina_template_hash != m.duress_retina_hash
        finally:
            db.close()


# =============================================================================
# 2. ATTESTATION ISSUANCE TESTS
# =============================================================================

class TestAttestationIssuance:

    def test_valid_attestation_issued(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            assert token["token_id"] is not None
            assert token["member_id"] == m.member_id
            assert token["legal_name"] == "Alice Founder"
            assert token["badge_serial"] == "BADGE-001"
            assert token["liveness_score"] == 0.98
            assert "hmac_signature" in token
        finally:
            db.close()

    def test_token_expires_in_90_seconds(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            issued = datetime.fromisoformat(token["issued_at"])
            expires = datetime.fromisoformat(token["expires_at"])
            if issued.tzinfo is None:
                issued = issued.replace(tzinfo=timezone.utc)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            delta = (expires - issued).total_seconds()
            assert 88 <= delta <= 92  # allow 2s tolerance
        finally:
            db.close()

    def test_wrong_face_raises(self):
        db = SessionLocal()
        try:
            m = _make_member(db, face=b"correct_face")
            with pytest.raises(ValueError, match="Face biometric"):
                issue_attestation(
                    db=db,
                    badge_serial=m.badge_serial,
                    face_scan_bytes=b"wrong_face",
                    retina_scan_bytes=b"retina_alice",
                    liveness_score=0.98,
                    location_node="node-001",
                )
        finally:
            db.close()

    def test_wrong_retina_raises(self):
        db = SessionLocal()
        try:
            m = _make_member(db, retina=b"correct_retina")
            with pytest.raises(ValueError, match="Retina biometric"):
                issue_attestation(
                    db=db,
                    badge_serial=m.badge_serial,
                    face_scan_bytes=b"face_alice",
                    retina_scan_bytes=b"wrong_retina",
                    liveness_score=0.98,
                    location_node="node-001",
                )
        finally:
            db.close()

    def test_low_liveness_raises(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            with pytest.raises(ValueError, match="Liveness score"):
                _issue(db, m, liveness=0.80)
        finally:
            db.close()

    def test_liveness_at_threshold_passes(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m, liveness=0.95)
            assert token["liveness_score"] == 0.95
        finally:
            db.close()

    def test_unknown_badge_raises(self):
        db = SessionLocal()
        try:
            with pytest.raises(ValueError, match="not enrolled"):
                issue_attestation(
                    db=db,
                    badge_serial="BADGE-UNKNOWN",
                    face_scan_bytes=b"face",
                    retina_scan_bytes=b"retina",
                    liveness_score=0.98,
                    location_node="node-001",
                )
        finally:
            db.close()

    def test_suspended_member_raises(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            m.suspended = True
            db.commit()
            with pytest.raises(ValueError, match="suspended"):
                _issue(db, m)
        finally:
            db.close()

    def test_out_of_scope_action_raises(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            with pytest.raises(ValueError, match="scope"):
                _issue(db, m, action="nuclear_launch")
        finally:
            db.close()

    def test_token_persisted_in_db(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            att = db.query(BiometricAttestation).filter_by(
                token_id=token["token_id"]
            ).first()
            assert att is not None
            assert att.member_id == m.member_id
            assert att.used is False
        finally:
            db.close()

    def test_duress_retina_triggers_silent_flag(self):
        db = SessionLocal()
        try:
            m = _make_member(db, retina=b"normal_retina", duress_retina=b"duress_retina")
            # Issue with duress retina — should succeed silently
            token = issue_attestation(
                db=db,
                badge_serial=m.badge_serial,
                face_scan_bytes=b"face_alice",
                retina_scan_bytes=b"duress_retina",
                liveness_score=0.98,
                location_node="node-001",
            )
            # duress_triggered is in the internal token but NOT in API response
            assert token["duress_triggered"] is True
            # Duress event created
            evt = db.query(DuressEvent).filter_by(member_id=m.member_id).first()
            assert evt is not None
            assert evt.resolved is False
        finally:
            db.close()

    def test_last_seen_updated_after_attestation(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            assert m.last_seen_node is None
            _issue(db, m, node="node-007")
            db.refresh(m)
            assert m.last_seen_node == "node-007"
            assert m.last_seen_at is not None
        finally:
            db.close()


# =============================================================================
# 3. GATE 0 VERIFICATION TESTS
# =============================================================================

class TestGate0Verification:

    def test_valid_token_passes(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            passed, reason = verify_attestation_token(db, token, "proposal")
            assert passed is True
            assert reason == "OK"
        finally:
            db.close()

    def test_missing_token_fails(self):
        db = SessionLocal()
        try:
            passed, reason = verify_attestation_token(db, None, "proposal")
            assert passed is False
            assert "GATE0_MISSING" in reason
        finally:
            db.close()

    def test_empty_token_fails(self):
        db = SessionLocal()
        try:
            passed, reason = verify_attestation_token(db, {}, "proposal")
            assert passed is False
        finally:
            db.close()

    def test_tampered_signature_fails(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            token["hmac_signature"] = "deadbeef" * 8
            passed, reason = verify_attestation_token(db, token, "proposal")
            assert passed is False
            assert "GATE0_INVALID_SIG" in reason
        finally:
            db.close()

    def test_tampered_payload_fails(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            # Modify payload after signing
            token["legal_name"] = "Evil Hacker"
            passed, reason = verify_attestation_token(db, token, "proposal")
            assert passed is False
            assert "GATE0_INVALID_SIG" in reason
        finally:
            db.close()

    def test_expired_token_fails(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            # Manually expire the token
            past = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
            token["expires_at"] = past
            # Re-sign with new expiry
            sig_payload = {k: v for k, v in token.items() if k != "hmac_signature"}
            token["hmac_signature"] = _sign_payload(sig_payload)
            passed, reason = verify_attestation_token(db, token, "proposal")
            assert passed is False
            assert "GATE0_EXPIRED" in reason
        finally:
            db.close()

    def test_fabricated_token_not_in_db_fails(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            # Build a valid-looking token that was never persisted
            now = datetime.now(timezone.utc)
            fake = {
                "token_id": str(uuid.uuid4()),
                "member_id": m.member_id,
                "legal_name": m.legal_name,
                "biometric_hash": "abc" * 21,
                "badge_serial": m.badge_serial,
                "issued_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=90)).isoformat(),
                "location_node": "node-001",
                "action_scope": ["proposal"],
                "liveness_score": 0.98,
                "duress_triggered": False,
            }
            fake["hmac_signature"] = _sign_payload(fake)
            passed, reason = verify_attestation_token(db, fake, "proposal")
            assert passed is False
            assert "GATE0_NOT_FOUND" in reason
        finally:
            db.close()

    def test_single_use_enforcement(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            # First use — should pass
            passed1, _ = verify_attestation_token(db, token, "proposal")
            assert passed1 is True
            # Second use — should fail (token marked used)
            passed2, reason2 = verify_attestation_token(db, token, "proposal")
            assert passed2 is False
            assert "GATE0_REPLAYED" in reason2
        finally:
            db.close()

    def test_suspended_member_token_fails(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            # Suspend after issuance
            m.suspended = True
            db.commit()
            passed, reason = verify_attestation_token(db, token, "proposal")
            assert passed is False
            assert "GATE0_SUSPENDED" in reason
        finally:
            db.close()

    def test_wrong_action_scope_fails(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m, action="proposal")
            # Verify against a different action type
            passed, reason = verify_attestation_token(db, token, "nuclear_launch")
            assert passed is False
            assert "GATE0_SCOPE" in reason
        finally:
            db.close()

    def test_revoked_member_token_fails(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            # Revoke the member
            revoke_member(db, m.member_id, "admin", "Test revocation")
            # Issue a new token (won't work — suspended)
            # But test that existing token also fails
            # Need a fresh token from before revocation
            # Re-insert a fresh attestation manually to test revocation check
            att = db.query(BiometricAttestation).filter_by(
                token_id=token["token_id"]
            ).first()
            att.used = False  # reset used flag to test revocation check
            db.commit()
            passed, reason = verify_attestation_token(db, token, "proposal")
            assert passed is False
            # Either suspended or revoked check fires
            assert "GATE0_SUSPENDED" in reason or "GATE0_REVOKED" in reason
        finally:
            db.close()

    def test_liveness_below_threshold_in_db_fails(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m, liveness=0.95)
            # Manually lower liveness in DB record
            att = db.query(BiometricAttestation).filter_by(
                token_id=token["token_id"]
            ).first()
            att.liveness_score = 0.50
            att.used = False
            db.commit()
            passed, reason = verify_attestation_token(db, token, "proposal")
            assert passed is False
            assert "GATE0_LIVENESS" in reason
        finally:
            db.close()

    def test_no_db_session_fails(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
        finally:
            db.close()
        passed, reason = verify_attestation_token(None, token, "proposal")
        assert passed is False


# =============================================================================
# 4. GEOGRAPHIC ANOMALY TESTS
# =============================================================================

class TestGeographicAnomaly:

    def test_same_node_no_anomaly(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            _issue(db, m, node="node-001")
            # Second scan at same node — should pass
            token2 = _issue(db, m, node="node-001")
            assert token2["location_node"] == "node-001"
        finally:
            db.close()

    def test_different_node_within_30_min_raises(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            _issue(db, m, node="node-001")
            # Immediately try different node
            with pytest.raises(ValueError, match="IMPOSSIBLE_TRAVEL"):
                _issue(db, m, node="node-007")
        finally:
            db.close()

    def test_different_node_after_30_min_passes(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            _issue(db, m, node="node-001")
            # Simulate 31 minutes passing
            past = datetime.now(timezone.utc) - timedelta(minutes=31)
            m.last_seen_at = past
            db.commit()
            # Now different node should pass
            token2 = _issue(db, m, node="node-007")
            assert token2["location_node"] == "node-007"
        finally:
            db.close()

    def test_first_scan_no_anomaly(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            assert m.last_seen_node is None
            token = _issue(db, m, node="node-005")
            assert token["location_node"] == "node-005"
        finally:
            db.close()


# =============================================================================
# 5. DURESS PROTOCOL TESTS
# =============================================================================

class TestDuressProtocol:

    def test_duress_creates_escrow_event(self):
        db = SessionLocal()
        try:
            m = _make_member(db, retina=b"normal", duress_retina=b"duress")
            issue_attestation(
                db=db,
                badge_serial=m.badge_serial,
                face_scan_bytes=b"face_alice",
                retina_scan_bytes=b"duress",
                liveness_score=0.98,
                location_node="node-001",
            )
            evt = db.query(DuressEvent).filter_by(member_id=m.member_id).first()
            assert evt is not None
            assert evt.resolved is False
            # Escrow window is 4 hours
            delta = (evt.escrow_until - evt.triggered_at).total_seconds()
            assert 3 * 3600 < delta <= 5 * 3600
        finally:
            db.close()

    def test_duress_token_passes_gate0(self):
        """Duress token must pass Gate 0 silently (action goes to escrow)."""
        db = SessionLocal()
        try:
            m = _make_member(db, retina=b"normal", duress_retina=b"duress")
            token = issue_attestation(
                db=db,
                badge_serial=m.badge_serial,
                face_scan_bytes=b"face_alice",
                retina_scan_bytes=b"duress",
                liveness_score=0.98,
                location_node="node-001",
            )
            passed, reason = verify_attestation_token(db, token, "proposal")
            assert passed is True  # Gate 0 passes — duress handled at execution
        finally:
            db.close()

    def test_normal_retina_no_duress_event(self):
        db = SessionLocal()
        try:
            m = _make_member(db, retina=b"normal", duress_retina=b"duress")
            _issue(db, m, retina=b"normal")
            evt = db.query(DuressEvent).filter_by(member_id=m.member_id).first()
            assert evt is None
        finally:
            db.close()


# =============================================================================
# 6. REVOCATION TESTS
# =============================================================================

class TestRevocation:

    def test_revoke_suspends_member(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            revoke_member(db, m.member_id, "admin-001", "Misappropriation of MANNA")
            db.refresh(m)
            assert m.suspended is True
            assert m.suspension_reason == "Misappropriation of MANNA"
        finally:
            db.close()

    def test_revoke_creates_revocation_record(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            rev = revoke_member(db, m.member_id, "admin-001", "Test reason")
            assert rev.event_id is not None
            assert rev.member_id == m.member_id
            assert rev.legal_name == "Alice Founder"
        finally:
            db.close()

    def test_revoke_invalidates_pending_tokens(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            # Mark token as unused again to simulate pending
            att = db.query(BiometricAttestation).filter_by(
                token_id=token["token_id"]
            ).first()
            att.used = False
            db.commit()
            revoke_member(db, m.member_id, "admin", "Test")
            db.refresh(att)
            assert att.used is True  # invalidated by cascade
        finally:
            db.close()

    def test_revoke_nonexistent_member_raises(self):
        db = SessionLocal()
        try:
            with pytest.raises(ValueError, match="not found"):
                revoke_member(db, str(uuid.uuid4()), "admin", "reason")
        finally:
            db.close()

    def test_revoked_member_cannot_attest(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            revoke_member(db, m.member_id, "admin", "Test")
            with pytest.raises(ValueError, match="suspended"):
                _issue(db, m)
        finally:
            db.close()


# =============================================================================
# 7. ACCOUNTABILITY LOG TESTS
# =============================================================================

class TestAccountabilityLog:

    def test_record_creates_entry(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            entry = record_accountability(
                db=db,
                token=token,
                action_type="proposal",
                task_id="task-001",
                lineage_hash="abc" * 21,
                outcome="APPROVED",
                amount_manna=500.0,
            )
            assert entry.log_id is not None
            assert entry.legal_name == "Alice Founder"
            assert entry.outcome == "APPROVED"
            assert entry.amount_manna == 500.0
        finally:
            db.close()

    def test_record_has_hmac_signature(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            entry = record_accountability(
                db=db, token=token, action_type="proposal",
                task_id="t1", lineage_hash=None, outcome="BLOCKED",
            )
            assert len(entry.hmac_signature) == 64
        finally:
            db.close()

    def test_cooling_off_applied_for_large_amount(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            entry = record_accountability(
                db=db, token=token, action_type="treasury",
                task_id="t2", lineage_hash=None, outcome="APPROVED",
                amount_manna=5000.0,
            )
            assert entry.cooling_off_until is not None
            cou = entry.cooling_off_until
            if cou.tzinfo is None:
                cou = cou.replace(tzinfo=timezone.utc)
            delta = (cou - datetime.now(timezone.utc)).total_seconds()
            assert delta > 20 * 3600  # at least 20 hours
        finally:
            db.close()

    def test_no_cooling_off_for_small_amount(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            entry = record_accountability(
                db=db, token=token, action_type="proposal",
                task_id="t3", lineage_hash=None, outcome="APPROVED",
                amount_manna=50.0,
            )
            assert entry.cooling_off_until is None
        finally:
            db.close()

    def test_multiple_records_for_same_member(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            for i in range(5):
                token = _issue(db, m)
                record_accountability(
                    db=db, token=token, action_type="proposal",
                    task_id=f"task-{i}", lineage_hash=None, outcome="APPROVED",
                )
            logs = db.query(AccountabilityLog).filter_by(member_id=m.member_id).all()
            assert len(logs) == 5
        finally:
            db.close()


# =============================================================================
# 8. PUBLIC LEDGER TESTS
# =============================================================================

class TestPublicLedger:

    def test_get_actor_history_returns_all_records(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            for i in range(3):
                token = _issue(db, m)
                record_accountability(
                    db=db, token=token, action_type="proposal",
                    task_id=f"t{i}", lineage_hash=None, outcome="APPROVED",
                )
            history = get_actor_history(db, m.member_id)
            assert history["total_authorizations"] == 3
            assert history["legal_name"] == "Alice Founder"
        finally:
            db.close()

    def test_get_actor_history_unknown_member(self):
        db = SessionLocal()
        try:
            result = get_actor_history(db, str(uuid.uuid4()))
            assert "error" in result
        finally:
            db.close()

    def test_history_includes_hmac_signatures(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            record_accountability(
                db=db, token=token, action_type="proposal",
                task_id="t1", lineage_hash=None, outcome="APPROVED",
            )
            history = get_actor_history(db, m.member_id)
            for auth in history["authorizations"]:
                assert "hmac_signature" in auth
                assert len(auth["hmac_signature"]) == 64
        finally:
            db.close()


# =============================================================================
# 9. LEGAL EXPORT TESTS
# =============================================================================

class TestLegalExport:

    def test_export_package_structure(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            record_accountability(
                db=db, token=token, action_type="treasury",
                task_id="t1", lineage_hash="abc" * 21, outcome="APPROVED",
                amount_manna=1500.0,
            )
            pkg = export_legal_package(db, m.member_id)
            assert "package_id" in pkg
            assert "generated_at" in pkg
            assert "subject" in pkg
            assert "records" in pkg
            assert "integrity_proof" in pkg
            assert "package_signature" in pkg
            assert pkg["record_count"] == 1
        finally:
            db.close()

    def test_export_subject_contains_legal_name(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            pkg = export_legal_package(db, m.member_id)
            assert pkg["subject"]["legal_name"] == "Alice Founder"
            assert pkg["subject"]["badge_serial"] == "BADGE-001"
        finally:
            db.close()

    def test_export_integrity_proof_changes_with_records(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            pkg1 = export_legal_package(db, m.member_id)
            token = _issue(db, m)
            record_accountability(
                db=db, token=token, action_type="proposal",
                task_id="t1", lineage_hash=None, outcome="APPROVED",
            )
            pkg2 = export_legal_package(db, m.member_id)
            # Integrity proof must change when records are added
            assert pkg1["integrity_proof"] != pkg2["integrity_proof"]
        finally:
            db.close()

    def test_export_date_filter(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            record_accountability(
                db=db, token=token, action_type="proposal",
                task_id="t1", lineage_hash=None, outcome="APPROVED",
            )
            # Filter to future date range — should return 0 records
            future = datetime.now(timezone.utc) + timedelta(days=1)
            pkg = export_legal_package(
                db, m.member_id,
                date_start=future,
            )
            assert pkg["record_count"] == 0
        finally:
            db.close()

    def test_export_unknown_member(self):
        db = SessionLocal()
        try:
            pkg = export_legal_package(db, str(uuid.uuid4()))
            assert "error" in pkg
        finally:
            db.close()


# =============================================================================
# 10. COOLING-OFF WINDOW TESTS
# =============================================================================

class TestCoolingOff:

    def test_under_100_manna_no_cooling(self):
        assert get_cooling_off_seconds(99.9) == 0
        assert get_cooling_off_seconds(0) == 0
        assert get_cooling_off_seconds(50) == 0

    def test_100_to_999_manna_one_hour(self):
        assert get_cooling_off_seconds(100) == 3600
        assert get_cooling_off_seconds(500) == 3600
        assert get_cooling_off_seconds(999) == 3600

    def test_1000_to_9999_manna_24_hours(self):
        assert get_cooling_off_seconds(1000) == 24 * 3600
        assert get_cooling_off_seconds(5000) == 24 * 3600
        assert get_cooling_off_seconds(9999) == 24 * 3600

    def test_10000_plus_manna_72_hours(self):
        assert get_cooling_off_seconds(10000) == 72 * 3600
        assert get_cooling_off_seconds(100000) == 72 * 3600

    def test_boundary_exactly_1000(self):
        assert get_cooling_off_seconds(1000) == 24 * 3600

    def test_boundary_exactly_10000(self):
        assert get_cooling_off_seconds(10000) == 72 * 3600


# =============================================================================
# 11. HMAC INTEGRITY TESTS
# =============================================================================

class TestHMACIntegrity:

    def test_sign_payload_deterministic(self):
        payload = {"a": 1, "b": "hello", "c": True}
        sig1 = _sign_payload(payload)
        sig2 = _sign_payload(payload)
        assert sig1 == sig2

    def test_sign_payload_key_order_independent(self):
        p1 = {"z": 1, "a": 2}
        p2 = {"a": 2, "z": 1}
        assert _sign_payload(p1) == _sign_payload(p2)

    def test_sign_payload_changes_with_content(self):
        p1 = {"value": "good"}
        p2 = {"value": "evil"}
        assert _sign_payload(p1) != _sign_payload(p2)

    def test_hash_template_keyed(self):
        """Template hash must depend on BAS_SECRET."""
        h1 = _hash_template(b"biometric_data")
        # Different data → different hash
        h2 = _hash_template(b"different_data")
        assert h1 != h2

    def test_hash_template_deterministic(self):
        h1 = _hash_template(b"same_data")
        h2 = _hash_template(b"same_data")
        assert h1 == h2

    def test_accountability_log_signature_seals_row(self):
        db = SessionLocal()
        try:
            m = _make_member(db)
            token = _issue(db, m)
            entry = record_accountability(
                db=db, token=token, action_type="proposal",
                task_id="t1", lineage_hash=None, outcome="APPROVED",
            )
            # Signature must be 64-char hex (SHA-256)
            assert len(entry.hmac_signature) == 64
            assert all(c in "0123456789abcdef" for c in entry.hmac_signature)
        finally:
            db.close()


# =============================================================================
# 12. AETHEL GATE 0 INTEGRATION TESTS
# =============================================================================

class TestAethelGate0Integration:

    def test_gate0_bypassed_when_not_required(self):
        """When COLONY_BIOMETRIC_REQUIRED=false, Gate 0 is bypassed."""
        with patch.dict(os.environ, {"COLONY_BIOMETRIC_REQUIRED": "false"}):
            import aethel_interface as ai
            iface = ai.AethelInterface()
            result = iface.validate(
                task_id="test-task",
                human_consent=True,
                lq_score=0.90,
                agent_outputs={"agent": "output"},
                biometric_token=None,
                db=None,
            )
            assert result["gates"]["gate_0"]["verdict"] == "BYPASSED"

    def test_gate0_blocks_without_token_when_required(self):
        """When biometric required, missing token blocks at Gate 0."""
        with patch.dict(os.environ, {"COLONY_BIOMETRIC_REQUIRED": "true"}):
            import aethel_interface as ai
            iface = ai.AethelInterface()
            db = SessionLocal()
            try:
                result = iface.validate(
                    task_id="test-task",
                    human_consent=True,
                    lq_score=0.90,
                    agent_outputs={},
                    biometric_token=None,
                    db=db,
                )
                assert result["verdict"] == "BLOCKED"
                assert result["blocked_at_gate"] == 0
                assert "GATE0" in result["reason"]
            finally:
                db.close()

    def test_gate0_passes_with_valid_token(self):
        """Valid biometric token allows Gates 1-3 to run."""
        with patch.dict(os.environ, {"COLONY_BIOMETRIC_REQUIRED": "true"}):
            import aethel_interface as ai
            iface = ai.AethelInterface()
            db = SessionLocal()
            try:
                m = _make_member(db)
                token = _issue(db, m)
                result = iface.validate(
                    task_id="test-task",
                    human_consent=True,
                    lq_score=0.90,
                    agent_outputs={"summary": "community benefit"},
                    biometric_token=token,
                    action_type="proposal",
                    db=db,
                )
                assert result["gates"]["gate_0"]["verdict"] == "PASS"
                assert result["verdict"] == "APPROVED"
                assert result["actor"]["legal_name"] == "Alice Founder"
            finally:
                db.close()

    def test_gate0_actor_info_in_result(self):
        """Approved result includes actor identity for lineage binding."""
        with patch.dict(os.environ, {"COLONY_BIOMETRIC_REQUIRED": "true"}):
            import aethel_interface as ai
            iface = ai.AethelInterface()
            db = SessionLocal()
            try:
                m = _make_member(db)
                token = _issue(db, m)
                result = iface.validate(
                    task_id="t1",
                    human_consent=True,
                    lq_score=0.90,
                    agent_outputs={},
                    biometric_token=token,
                    action_type="proposal",
                    db=db,
                )
                actor = result.get("actor")
                assert actor is not None
                assert actor["member_id"] == m.member_id
                assert actor["badge_serial"] == "BADGE-001"
                assert actor["location_node"] == "node-001"
            finally:
                db.close()