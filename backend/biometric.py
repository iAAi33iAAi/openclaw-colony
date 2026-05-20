"""
OpenClaw Colony — Biometric Accountability Layer
=================================================
Implements the full biometric non-repudiation stack:

  ColonyMember        — enrolled member registry (biometric templates)
  BiometricAttestation — short-lived signed proof-of-presence tokens
  AccountabilityLog   — append-only public ledger of every authorized action
  DuressEvent         — silent duress alerts
  RevocationEvent     — federation-wide ban records

Gate 0 logic:
  verify_attestation_token() — called by Aethel before Gates 1-3

Enrollment:
  enroll_member()     — witnessed enrollment ceremony
  issue_attestation() — scanner calls this to produce a 90-second token

Accountability:
  record_accountability() — called after every Gate 0 pass
  get_actor_history()     — public ledger query
  export_legal_package()  — court-admissible evidence export
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float,
    Integer, LargeBinary, String, Text,
    event as sa_event,
)
from sqlalchemy.orm import Session

from db import Base, SessionLocal, engine

log = logging.getLogger("colony.biometric")

# ── Configuration ────────────────────────────────────────────────────────────

# Secret used to sign/verify attestation tokens (HMAC-SHA256).
# In production: load from HSM or secrets manager.
# Secret used to sign/verify attestation tokens (HMAC-SHA256).
# In production: load from HSM or secrets manager via COLONY_BAS_SECRET env var.
#
# ⚠️  SECURITY WARNING: If COLONY_BAS_SECRET is not set, a random ephemeral
# secret is generated at import time.  This means:
#   • Every process restart invalidates all existing tokens.
#   • Tokens cannot be verified across multiple worker processes.
#   • This is acceptable ONLY for single-process local development.
# Set COLONY_BAS_SECRET to a stable, HSM-backed value in staging and production.
_bas_secret_raw = os.environ.get("COLONY_BAS_SECRET", "")
if not _bas_secret_raw:
    import logging as _logging
    _logging.getLogger("colony.biometric").warning(
        "COLONY_BAS_SECRET is not set. Using an ephemeral random secret. "
        "All biometric tokens will be invalidated on process restart. "
        "Set COLONY_BAS_SECRET to a stable HSM-backed value in production."
    )
    _bas_secret_raw = secrets.token_hex(32)
BAS_SECRET: str = _bas_secret_raw

# Token lifetime in seconds (90 seconds — cannot be replayed)
ATTESTATION_TTL = int(os.environ.get("COLONY_ATTESTATION_TTL", "90"))

# Minimum liveness score to accept (0.0–1.0)
LIVENESS_THRESHOLD = float(os.environ.get("COLONY_LIVENESS_THRESHOLD", "0.95"))

# Cooling-off windows by MANNA amount
COOLING_OFF_RULES = [
    (10_000, 72 * 3600),   # ≥ 10 000 MANNA → 72 hours
    (1_000,  24 * 3600),   # ≥  1 000 MANNA → 24 hours
    (100,     3600),        # ≥    100 MANNA →  1 hour
    (0,          0),        # <    100 MANNA → immediate
]

# ── DB Models ────────────────────────────────────────────────────────────────

class ColonyMember(Base):
    """Enrolled member registry — biometric templates + role."""
    __tablename__ = "colony_members"
    __table_args__ = {"extend_existing": True}

    member_id         = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    legal_name        = Column(String(256), nullable=False)
    enrolled_at       = Column(DateTime, nullable=False,
                               default=lambda: datetime.now(timezone.utc))
    enrolled_by       = Column(String(36), nullable=False)   # member_id of enroller
    witness_ids       = Column(Text, nullable=False)          # JSON list of 3 witness member_ids
    badge_serial      = Column(String(64), unique=True, nullable=False)
    role              = Column(String(32), default="member")  # member | steward | auditor | architect
    suspended         = Column(Boolean, default=False)
    suspended_at      = Column(DateTime, nullable=True)
    suspended_by      = Column(String(36), nullable=True)
    suspension_reason = Column(Text, nullable=True)

    # Biometric templates — stored as HMAC-SHA256 of raw template bytes.
    # Raw biometric data NEVER persisted; only the keyed hash.
    face_template_hash    = Column(String(64), nullable=False)
    retina_template_hash  = Column(String(64), nullable=False)
    # Duress retina hash — known only to the member, used to trigger silent alert
    duress_retina_hash    = Column(String(64), nullable=True)
    fingerprint_hash      = Column(String(64), nullable=True)
    voice_hash            = Column(String(64), nullable=True)

    # Action scope — JSON list of permitted action types
    action_scope      = Column(Text, default='["proposal","treasury"]')

    # Last known location (updated on each scan)
    last_seen_node    = Column(String(64), nullable=True)
    last_seen_at      = Column(DateTime, nullable=True)


class BiometricAttestation(Base):
    """
    Short-lived proof-of-presence token issued by the scanner.
    Expires after ATTESTATION_TTL seconds.
    Stored for audit trail even after expiry.
    """
    __tablename__ = "biometric_attestations"
    __table_args__ = {"extend_existing": True}

    id               = Column(Integer, primary_key=True, index=True)
    token_id         = Column(String(36), unique=True, nullable=False,
                              default=lambda: str(uuid.uuid4()))
    member_id        = Column(String(36), nullable=False, index=True)
    badge_serial     = Column(String(64), nullable=False)
    biometric_hash   = Column(String(64), nullable=False)  # HMAC of face+retina at scan time
    liveness_score   = Column(Float, nullable=False)
    location_node    = Column(String(64), nullable=False)
    action_scope     = Column(Text, nullable=False)         # JSON list
    issued_at        = Column(DateTime, nullable=False,
                              default=lambda: datetime.now(timezone.utc))
    expires_at       = Column(DateTime, nullable=False)
    hmac_signature   = Column(String(64), nullable=False)   # HMAC-SHA256 of token payload
    used             = Column(Boolean, default=False)        # single-use enforcement
    duress_triggered = Column(Boolean, default=False)        # silent duress flag


class AccountabilityLog(Base):
    """
    Append-only public ledger — every Gate 0 pass is recorded here.
    Linked to the lineage chain via lineage_hash.
    Court-admissible: contains legal name, biometric proof, timestamp, location.
    """
    __tablename__ = "accountability_log"
    __table_args__ = {"extend_existing": True}

    id               = Column(Integer, primary_key=True, index=True)
    log_id           = Column(String(36), unique=True, nullable=False,
                              default=lambda: str(uuid.uuid4()))
    member_id        = Column(String(36), nullable=False, index=True)
    legal_name       = Column(String(256), nullable=False)
    badge_serial     = Column(String(64), nullable=False)
    biometric_hash   = Column(String(64), nullable=False)
    token_id         = Column(String(36), nullable=False)
    action_type      = Column(String(64), nullable=False)
    task_id          = Column(String(36), nullable=True, index=True)
    lineage_hash     = Column(String(64), nullable=True)
    amount_manna     = Column(Float, nullable=True)
    location_node    = Column(String(64), nullable=False)
    scan_timestamp   = Column(DateTime, nullable=False)
    outcome          = Column(String(32), nullable=False)   # APPROVED | BLOCKED | PENDING
    cooling_off_until = Column(DateTime, nullable=True)
    hmac_signature   = Column(String(64), nullable=False)   # seals the full log row
    duress_triggered = Column(Boolean, default=False)


class DuressEvent(Base):
    """Silent duress alert — created when member uses duress retina scan."""
    __tablename__ = "duress_events"
    __table_args__ = {"extend_existing": True}

    id           = Column(Integer, primary_key=True, index=True)
    event_id     = Column(String(36), unique=True, nullable=False,
                          default=lambda: str(uuid.uuid4()))
    member_id    = Column(String(36), nullable=False, index=True)
    legal_name   = Column(String(256), nullable=False)
    location_node = Column(String(64), nullable=False)
    triggered_at = Column(DateTime, nullable=False,
                          default=lambda: datetime.now(timezone.utc))
    task_id      = Column(String(36), nullable=True)
    # Action is held in escrow — stewards must release or freeze
    escrow_until = Column(DateTime, nullable=False)
    resolved     = Column(Boolean, default=False)
    resolved_by  = Column(String(36), nullable=True)
    resolution   = Column(String(32), nullable=True)  # RELEASED | FROZEN


class RevocationEvent(Base):
    """Federation-wide ban record — propagated to all nodes."""
    __tablename__ = "revocation_events"
    __table_args__ = {"extend_existing": True}

    id            = Column(Integer, primary_key=True, index=True)
    event_id      = Column(String(36), unique=True, nullable=False,
                           default=lambda: str(uuid.uuid4()))
    member_id     = Column(String(36), nullable=False, index=True)
    legal_name    = Column(String(256), nullable=False)
    badge_serial  = Column(String(64), nullable=False)
    biometric_hash = Column(String(64), nullable=False)
    revoked_at    = Column(DateTime, nullable=False,
                           default=lambda: datetime.now(timezone.utc))
    revoked_by    = Column(String(36), nullable=False)
    reason        = Column(Text, nullable=False)
    propagated    = Column(Boolean, default=False)  # True once all nodes notified


# ── Init ─────────────────────────────────────────────────────────────────────

def init_biometric_tables() -> None:
    """Create all biometric tables. Safe to call multiple times."""
    Base.metadata.create_all(bind=engine, checkfirst=True)


# ── Token helpers ─────────────────────────────────────────────────────────────

def _sign_payload(payload: dict) -> str:
    """HMAC-SHA256 sign a dict payload. Returns hex digest."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        BAS_SECRET.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()


def _hash_template(raw_bytes: bytes) -> str:
    """Keyed hash of a biometric template. Never store raw bytes."""
    return hmac.new(
        BAS_SECRET.encode(),
        raw_bytes,
        hashlib.sha256,
    ).hexdigest()


def _biometric_hash(face_bytes: bytes, retina_bytes: bytes) -> str:
    """Combined hash of face + retina templates."""
    combined = face_bytes + b":" + retina_bytes
    return _hash_template(combined)


# ── Enrollment ────────────────────────────────────────────────────────────────

def enroll_member(
    db: Session,
    legal_name: str,
    badge_serial: str,
    face_template_bytes: bytes,
    retina_template_bytes: bytes,
    enrolled_by: str,
    witness_ids: list[str],
    role: str = "member",
    duress_retina_bytes: Optional[bytes] = None,
    fingerprint_bytes: Optional[bytes] = None,
    voice_bytes: Optional[bytes] = None,
    action_scope: Optional[list[str]] = None,
) -> ColonyMember:
    """
    Enroll a new colony member.
    Requires 3 witnesses (witness_ids must be existing active member_ids).
    Raw biometric bytes are hashed immediately and never stored.
    """
    if len(witness_ids) < 3:
        raise ValueError("Enrollment requires at least 3 witnesses.")

    # Verify witnesses exist and are active
    for wid in witness_ids:
        w = db.query(ColonyMember).filter_by(member_id=wid, suspended=False).first()
        if not w:
            raise ValueError(f"Witness {wid} is not an active colony member.")

    # Check badge not already in use
    existing = db.query(ColonyMember).filter_by(badge_serial=badge_serial).first()
    if existing:
        raise ValueError(f"Badge serial {badge_serial} already enrolled.")

    member = ColonyMember(
        member_id=str(uuid.uuid4()),
        legal_name=legal_name,
        enrolled_by=enrolled_by,
        witness_ids=json.dumps(witness_ids),
        badge_serial=badge_serial,
        role=role,
        face_template_hash=_hash_template(face_template_bytes),
        retina_template_hash=_hash_template(retina_template_bytes),
        duress_retina_hash=_hash_template(duress_retina_bytes) if duress_retina_bytes else None,
        fingerprint_hash=_hash_template(fingerprint_bytes) if fingerprint_bytes else None,
        voice_hash=_hash_template(voice_bytes) if voice_bytes else None,
        action_scope=json.dumps(action_scope or ["proposal", "treasury"]),
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    log.info("[BIOMETRIC] Enrolled member %s (%s) with role=%s",
             member.member_id, legal_name, role)
    return member


# ── Attestation issuance ──────────────────────────────────────────────────────

def issue_attestation(
    db: Session,
    badge_serial: str,
    face_scan_bytes: bytes,
    retina_scan_bytes: bytes,
    liveness_score: float,
    location_node: str,
    action_type: str = "proposal",
) -> dict:
    """
    Called by the physical scanner after capturing biometrics.
    Verifies identity, checks liveness, issues a 90-second signed token.

    Returns:
        {
          "token_id": str,
          "member_id": str,
          "legal_name": str,
          "biometric_hash": str,
          "badge_serial": str,
          "issued_at": ISO str,
          "expires_at": ISO str,
          "location_node": str,
          "action_scope": list,
          "liveness_score": float,
          "hmac_signature": str,
          "duress_triggered": bool   ← True if duress retina used (silent)
        }

    Raises ValueError on any verification failure.
    """
    # 1. Find member by badge
    member = db.query(ColonyMember).filter_by(badge_serial=badge_serial).first()
    if not member:
        raise ValueError(f"Badge {badge_serial} not enrolled.")
    if member.suspended:
        raise ValueError(f"Member {member.member_id} is suspended.")

    # 2. Liveness check
    if liveness_score < LIVENESS_THRESHOLD:
        raise ValueError(
            f"Liveness score {liveness_score:.3f} below threshold {LIVENESS_THRESHOLD}."
        )

    # 3. Biometric match — face
    face_hash = _hash_template(face_scan_bytes)
    if not hmac.compare_digest(face_hash, member.face_template_hash):
        raise ValueError("Face biometric does not match enrolled template.")

    # 4. Biometric match — retina (normal or duress)
    retina_hash = _hash_template(retina_scan_bytes)
    duress_triggered = False

    if hmac.compare_digest(retina_hash, member.retina_template_hash):
        duress_triggered = False
    elif member.duress_retina_hash and hmac.compare_digest(
        retina_hash, member.duress_retina_hash
    ):
        duress_triggered = True
        log.warning("[BIOMETRIC][DURESS] Member %s (%s) triggered duress protocol at %s",
                    member.member_id, member.legal_name, location_node)
    else:
        raise ValueError("Retina biometric does not match enrolled template.")

    # 5. Action scope check
    scope = json.loads(member.action_scope)
    if action_type not in scope:
        raise ValueError(
            f"Action type '{action_type}' not in member's permitted scope: {scope}"
        )

    # 6. Geographic anomaly check
    _check_geographic_anomaly(db, member, location_node)

    # 7. Build token
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ATTESTATION_TTL)
    bio_hash = _biometric_hash(face_scan_bytes, retina_scan_bytes)

    token_payload = {
        "token_id": str(uuid.uuid4()),
        "member_id": member.member_id,
        "legal_name": member.legal_name,
        "biometric_hash": bio_hash,
        "badge_serial": badge_serial,
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "location_node": location_node,
        "action_scope": scope,
        "liveness_score": liveness_score,
        "duress_triggered": duress_triggered,
    }
    token_payload["hmac_signature"] = _sign_payload(token_payload)

    # 8. Persist attestation record
    att = BiometricAttestation(
        token_id=token_payload["token_id"],
        member_id=member.member_id,
        badge_serial=badge_serial,
        biometric_hash=bio_hash,
        liveness_score=liveness_score,
        location_node=location_node,
        action_scope=json.dumps(scope),
        issued_at=now,
        expires_at=expires,
        hmac_signature=token_payload["hmac_signature"],
        duress_triggered=duress_triggered,
    )
    db.add(att)

    # 9. Update member last-seen
    member.last_seen_node = location_node
    member.last_seen_at = now
    db.commit()

    # 10. If duress — create escrow event (4-hour hold)
    if duress_triggered:
        _create_duress_event(db, member, location_node, now)

    return token_payload


# ── Gate 0 verification ───────────────────────────────────────────────────────

def verify_attestation_token(
    db: Session,
    token: dict,
    required_action_type: str = "proposal",
) -> tuple[bool, str]:
    """
    Gate 0: Verify a biometric attestation token before allowing any action.

    Returns:
        (True, "OK") on success
        (False, reason_string) on failure

    Checks:
      1. Token structure present
      2. HMAC signature valid (not tampered)
      3. Not expired (≤ 90 seconds old)
      4. Token exists in DB (not fabricated)
      5. Not already used (single-use)
      6. Member enrolled and not suspended
      7. Badge active
      8. Action scope covers required_action_type
      9. Liveness score ≥ threshold
      10. Member not in revocation list
    """
    if not token:
        return False, "GATE0_MISSING: No biometric attestation token provided."

    # 1. Verify HMAC signature
    provided_sig = token.get("hmac_signature", "")
    payload_to_verify = {k: v for k, v in token.items() if k != "hmac_signature"}
    expected_sig = _sign_payload(payload_to_verify)
    if not hmac.compare_digest(provided_sig, expected_sig):
        return False, "GATE0_INVALID_SIG: Token signature verification failed."

    # 2. Expiry check
    try:
        expires_at = datetime.fromisoformat(token["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return False, "GATE0_MALFORMED: Token missing or invalid expires_at."

    now = datetime.now(timezone.utc)
    if now > expires_at:
        return False, f"GATE0_EXPIRED: Token expired at {expires_at.isoformat()}."

    # 3. DB lookup — token must exist
    if db is None:
        return False, "GATE0_NO_DB: No database session provided."
    token_id = token.get("token_id")
    att = db.query(BiometricAttestation).filter_by(token_id=token_id).first()
    if not att:
        return False, "GATE0_NOT_FOUND: Token not found in attestation registry."

    # 4. Single-use enforcement
    if att.used:
        return False, "GATE0_REPLAYED: Token has already been used."

    # 5. Member check
    member = db.query(ColonyMember).filter_by(member_id=att.member_id).first()
    if not member:
        return False, "GATE0_NO_MEMBER: Member not found in registry."
    if member.suspended:
        return False, f"GATE0_SUSPENDED: Member {member.legal_name} is suspended."

    # 6. Badge check
    if member.badge_serial != att.badge_serial:
        return False, "GATE0_BADGE_MISMATCH: Badge serial mismatch."

    # 7. Action scope
    scope = json.loads(att.action_scope)
    if required_action_type not in scope:
        return False, (
            f"GATE0_SCOPE: Action '{required_action_type}' not in "
            f"member's permitted scope {scope}."
        )

    # 8. Liveness
    if att.liveness_score < LIVENESS_THRESHOLD:
        return False, (
            f"GATE0_LIVENESS: Score {att.liveness_score:.3f} "
            f"below threshold {LIVENESS_THRESHOLD}."
        )

    # 9. Revocation check
    rev = db.query(RevocationEvent).filter_by(member_id=att.member_id).first()
    if rev:
        return False, (
            f"GATE0_REVOKED: Member {member.legal_name} is federation-banned "
            f"(revoked {rev.revoked_at.isoformat()})."
        )

    # 10. Duress check — if duress, token is valid but action goes to escrow
    if att.duress_triggered:
        log.warning("[GATE0][DURESS] Duress token used by %s — action will be escrowed.",
                    member.legal_name)
        # Still passes Gate 0 — duress is handled at execution time

    # Mark token as used
    att.used = True
    db.commit()

    return True, "OK"


# ── Accountability recording ──────────────────────────────────────────────────

def record_accountability(
    db: Session,
    token: dict,
    action_type: str,
    task_id: Optional[str],
    lineage_hash: Optional[str],
    outcome: str,
    amount_manna: Optional[float] = None,
) -> AccountabilityLog:
    """
    Write an immutable accountability record after Gate 0 passes.
    Called regardless of whether Gates 1-3 pass or fail.
    """
    now = datetime.now(timezone.utc)

    # Cooling-off window
    cooling_until = None
    if amount_manna is not None:
        for threshold, seconds in COOLING_OFF_RULES:
            if amount_manna >= threshold:
                if seconds > 0:
                    cooling_until = now + timedelta(seconds=seconds)
                break

    row_data = {
        "log_id": str(uuid.uuid4()),
        "member_id": token.get("member_id", ""),
        "legal_name": token.get("legal_name", ""),
        "badge_serial": token.get("badge_serial", ""),
        "biometric_hash": token.get("biometric_hash", ""),
        "token_id": token.get("token_id", ""),
        "action_type": action_type,
        "task_id": task_id,
        "lineage_hash": lineage_hash,
        "amount_manna": amount_manna,
        "location_node": token.get("location_node", ""),
        "scan_timestamp": token.get("issued_at", now.isoformat()),
        "outcome": outcome,
        "cooling_off_until": cooling_until.isoformat() if cooling_until else None,
        "duress_triggered": token.get("duress_triggered", False),
    }
    row_data["hmac_signature"] = _sign_payload(row_data)

    entry = AccountabilityLog(
        log_id=row_data["log_id"],
        member_id=row_data["member_id"],
        legal_name=row_data["legal_name"],
        badge_serial=row_data["badge_serial"],
        biometric_hash=row_data["biometric_hash"],
        token_id=row_data["token_id"],
        action_type=action_type,
        task_id=task_id,
        lineage_hash=lineage_hash,
        amount_manna=amount_manna,
        location_node=row_data["location_node"],
        scan_timestamp=datetime.fromisoformat(row_data["scan_timestamp"])
                       if isinstance(row_data["scan_timestamp"], str)
                       else row_data["scan_timestamp"],
        outcome=outcome,
        cooling_off_until=cooling_until,
        hmac_signature=row_data["hmac_signature"],
        duress_triggered=row_data["duress_triggered"],
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


# ── Public ledger query ───────────────────────────────────────────────────────

def get_actor_history(db: Session, member_id: str) -> dict:
    """Return full accountability history for a member (public ledger)."""
    member = db.query(ColonyMember).filter_by(member_id=member_id).first()
    if not member:
        return {"error": "Member not found."}

    logs = (
        db.query(AccountabilityLog)
        .filter_by(member_id=member_id)
        .order_by(AccountabilityLog.id.asc())
        .all()
    )

    return {
        "member_id": member_id,
        "legal_name": member.legal_name,
        "role": member.role,
        "enrolled_at": member.enrolled_at.isoformat(),
        "suspended": member.suspended,
        "total_authorizations": len(logs),
        "authorizations": [
            {
                "log_id": e.log_id,
                "timestamp": e.scan_timestamp.isoformat(),
                "action_type": e.action_type,
                "task_id": e.task_id,
                "lineage_hash": e.lineage_hash,
                "amount_manna": e.amount_manna,
                "location": e.location_node,
                "badge_serial": e.badge_serial,
                "outcome": e.outcome,
                "cooling_off_until": (
                    e.cooling_off_until.isoformat() if e.cooling_off_until else None
                ),
                "duress_triggered": e.duress_triggered,
                "hmac_signature": e.hmac_signature,
            }
            for e in logs
        ],
    }


# ── Legal export ──────────────────────────────────────────────────────────────

def export_legal_package(
    db: Session,
    member_id: str,
    date_start: Optional[datetime] = None,
    date_end: Optional[datetime] = None,
    action_types: Optional[list[str]] = None,
) -> dict:
    """
    Generate a court-admissible evidence package for a member.
    Includes:
      - Member enrollment record
      - Full filtered accountability log
      - Cryptographic integrity proof
      - Chain-of-custody metadata
    """
    member = db.query(ColonyMember).filter_by(member_id=member_id).first()
    if not member:
        return {"error": "Member not found."}

    query = db.query(AccountabilityLog).filter_by(member_id=member_id)
    if date_start:
        query = query.filter(AccountabilityLog.scan_timestamp >= date_start)
    if date_end:
        query = query.filter(AccountabilityLog.scan_timestamp <= date_end)
    if action_types:
        query = query.filter(AccountabilityLog.action_type.in_(action_types))

    logs = query.order_by(AccountabilityLog.id.asc()).all()

    # Integrity proof — hash of all log row signatures in order
    chain = hashlib.sha256(
        ":".join(e.hmac_signature for e in logs).encode()
    ).hexdigest()

    package = {
        "package_id": str(uuid.uuid4()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "OpenClaw Colony Accountability Layer v1.0",
        "subject": {
            "member_id": member.member_id,
            "legal_name": member.legal_name,
            "role": member.role,
            "enrolled_at": member.enrolled_at.isoformat(),
            "badge_serial": member.badge_serial,
            "suspended": member.suspended,
            "suspension_reason": member.suspension_reason,
        },
        "filter_applied": {
            "date_start": date_start.isoformat() if date_start else None,
            "date_end": date_end.isoformat() if date_end else None,
            "action_types": action_types,
        },
        "record_count": len(logs),
        "records": [
            {
                "log_id": e.log_id,
                "scan_timestamp": e.scan_timestamp.isoformat(),
                "action_type": e.action_type,
                "task_id": e.task_id,
                "lineage_hash": e.lineage_hash,
                "amount_manna": e.amount_manna,
                "location_node": e.location_node,
                "badge_serial": e.badge_serial,
                "biometric_hash": e.biometric_hash,
                "outcome": e.outcome,
                "duress_triggered": e.duress_triggered,
                "hmac_signature": e.hmac_signature,
            }
            for e in logs
        ],
        "integrity_proof": chain,
        "verification_instructions": (
            "To verify: for each record, recompute HMAC-SHA256 of the record fields "
            "(excluding hmac_signature) using the colony's BAS public key. "
            "Then hash all signatures in order to reproduce integrity_proof."
        ),
    }

    # Sign the entire package
    package["package_signature"] = _sign_payload(
        {"integrity_proof": chain, "record_count": len(logs),
         "member_id": member_id, "generated_at": package["generated_at"]}
    )

    return package


# ── Revocation ────────────────────────────────────────────────────────────────

def revoke_member(
    db: Session,
    member_id: str,
    revoked_by: str,
    reason: str,
) -> RevocationEvent:
    """
    Immediately suspend a member and create a federation-wide revocation record.
    Triggers revocation cascade:
      1. Badge invalidated (suspended flag)
      2. Revocation record created
      3. All pending attestations marked used (invalidated)
    """
    member = db.query(ColonyMember).filter_by(member_id=member_id).first()
    if not member:
        raise ValueError(f"Member {member_id} not found.")

    now = datetime.now(timezone.utc)
    member.suspended = True
    member.suspended_at = now
    member.suspended_by = revoked_by
    member.suspension_reason = reason

    # Invalidate all unused attestation tokens
    db.query(BiometricAttestation).filter_by(
        member_id=member_id, used=False
    ).update({"used": True})

    rev = RevocationEvent(
        member_id=member_id,
        legal_name=member.legal_name,
        badge_serial=member.badge_serial,
        biometric_hash=member.face_template_hash,
        revoked_by=revoked_by,
        reason=reason,
    )
    db.add(rev)
    db.commit()
    db.refresh(rev)

    log.warning("[BIOMETRIC][REVOKE] Member %s (%s) revoked by %s. Reason: %s",
                member_id, member.legal_name, revoked_by, reason)
    return rev


# ── Geographic anomaly detection ──────────────────────────────────────────────

def _check_geographic_anomaly(
    db: Session,
    member: ColonyMember,
    new_location: str,
) -> None:
    """
    Detect impossible travel: if member was seen at a different node
    within the last 30 minutes, flag as anomaly.
    Raises ValueError if impossible travel detected.
    """
    if not member.last_seen_at or not member.last_seen_node:
        return
    if member.last_seen_node == new_location:
        return

    now = datetime.now(timezone.utc)
    last = member.last_seen_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)

    elapsed_minutes = (now - last).total_seconds() / 60
    if elapsed_minutes < 30:
        log.error(
            "[BIOMETRIC][ANOMALY] IMPOSSIBLE_TRAVEL: Member %s (%s) "
            "was at %s %d minutes ago, now attempting auth at %s.",
            member.member_id, member.legal_name,
            member.last_seen_node, int(elapsed_minutes), new_location,
        )
        raise ValueError(
            f"GATE0_IMPOSSIBLE_TRAVEL: Member {member.legal_name} was seen at "
            f"{member.last_seen_node} {int(elapsed_minutes)} minutes ago. "
            f"Cannot authenticate at {new_location}."
        )


# ── Duress event creation ─────────────────────────────────────────────────────

def _create_duress_event(
    db: Session,
    member: ColonyMember,
    location_node: str,
    triggered_at: datetime,
    task_id: Optional[str] = None,
) -> DuressEvent:
    """Create a 4-hour escrow duress event and alert stewards."""
    escrow_until = triggered_at + timedelta(hours=4)
    evt = DuressEvent(
        member_id=member.member_id,
        legal_name=member.legal_name,
        location_node=location_node,
        triggered_at=triggered_at,
        task_id=task_id,
        escrow_until=escrow_until,
    )
    db.add(evt)
    db.commit()
    db.refresh(evt)
    log.critical(
        "[DURESS][ALERT] Stewards: member %s (%s) at %s triggered duress. "
        "Action escrowed until %s. Event ID: %s",
        member.member_id, member.legal_name, location_node,
        escrow_until.isoformat(), evt.event_id,
    )
    return evt


# ── Cooling-off helper ────────────────────────────────────────────────────────

def get_cooling_off_seconds(amount_manna: float) -> int:
    """Return the cooling-off window in seconds for a given MANNA amount."""
    for threshold, seconds in COOLING_OFF_RULES:
        if amount_manna >= threshold:
            return seconds
    return 0