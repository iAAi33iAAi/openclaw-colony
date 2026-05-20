"""
OpenClaw Colony — Biometric Accountability Routes
==================================================
FastAPI router exposing:

  POST /biometric/enroll          — witnessed member enrollment
  POST /biometric/attest          — scanner issues attestation token
  GET  /biometric/member/{id}     — public accountability ledger
  GET  /biometric/history/{id}    — full action history
  POST /biometric/legal-export    — court-admissible evidence package
  POST /biometric/revoke/{id}     — revoke member (steward only)
  GET  /biometric/duress          — active duress events (steward only)
  POST /biometric/duress/{id}/resolve — resolve duress escrow
  GET  /biometric/revocations     — federation revocation list
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from auth import require_admin
from biometric import (
    init_biometric_tables,
    enroll_member,
    issue_attestation,
    verify_attestation_token,
    record_accountability,
    get_actor_history,
    export_legal_package,
    revoke_member,
    ColonyMember,
    BiometricAttestation,
    DuressEvent,
    RevocationEvent,
)

log = logging.getLogger("colony.biometric_routes")
router = APIRouter(prefix="/biometric", tags=["biometric"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class EnrollRequest(BaseModel):
    legal_name: str
    badge_serial: str
    # Biometric templates submitted as hex strings (from scanner hardware)
    face_template_hex: str
    retina_template_hex: str
    enrolled_by: str                    # member_id of enroller
    witness_ids: list[str]              # exactly 3 active member_ids
    role: str = "member"
    duress_retina_hex: Optional[str] = None
    fingerprint_hex: Optional[str] = None
    voice_hex: Optional[str] = None
    action_scope: Optional[list[str]] = None


class AttestRequest(BaseModel):
    badge_serial: str
    face_scan_hex: str
    retina_scan_hex: str
    liveness_score: float
    location_node: str
    action_type: str = "proposal"


class LegalExportRequest(BaseModel):
    member_id: str
    date_start: Optional[str] = None    # ISO datetime string
    date_end: Optional[str] = None
    action_types: Optional[list[str]] = None


class RevokeRequest(BaseModel):
    reason: str
    revoked_by: str                     # member_id of steward performing revocation


class ResolveDuressRequest(BaseModel):
    resolution: str                     # RELEASED | FROZEN
    resolved_by: str                    # member_id of steward


# ── Enrollment ────────────────────────────────────────────────────────────────

@router.post("/enroll")
def enroll(
    req: EnrollRequest,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Enroll a new colony member.
    Requires admin key + 3 witness member_ids.
    Raw biometric bytes are hashed immediately; never stored.
    """
    try:
        member = enroll_member(
            db=db,
            legal_name=req.legal_name,
            badge_serial=req.badge_serial,
            face_template_bytes=bytes.fromhex(req.face_template_hex),
            retina_template_bytes=bytes.fromhex(req.retina_template_hex),
            enrolled_by=req.enrolled_by,
            witness_ids=req.witness_ids,
            role=req.role,
            duress_retina_bytes=(
                bytes.fromhex(req.duress_retina_hex)
                if req.duress_retina_hex else None
            ),
            fingerprint_bytes=(
                bytes.fromhex(req.fingerprint_hex)
                if req.fingerprint_hex else None
            ),
            voice_bytes=(
                bytes.fromhex(req.voice_hex)
                if req.voice_hex else None
            ),
            action_scope=req.action_scope,
        )
        return {
            "status": "enrolled",
            "member_id": member.member_id,
            "legal_name": member.legal_name,
            "role": member.role,
            "enrolled_at": member.enrolled_at.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Attestation issuance ──────────────────────────────────────────────────────

@router.post("/attest")
def attest(
    req: AttestRequest,
    db: Session = Depends(get_db),
):
    """
    Called by the physical scanner after capturing biometrics.
    Returns a 90-second signed attestation token.
    No admin key required — scanner hardware authenticates via network isolation.
    """
    try:
        token = issue_attestation(
            db=db,
            badge_serial=req.badge_serial,
            face_scan_bytes=bytes.fromhex(req.face_scan_hex),
            retina_scan_bytes=bytes.fromhex(req.retina_scan_hex),
            liveness_score=req.liveness_score,
            location_node=req.location_node,
            action_type=req.action_type,
        )
        # Never expose duress_triggered in response (silent protocol)
        safe_token = {k: v for k, v in token.items() if k != "duress_triggered"}
        return {"status": "issued", "token": safe_token}
    except ValueError as e:
        # Return generic error — do not reveal which check failed
        log.warning("[BIOMETRIC][ATTEST] Attestation failed: %s", e)
        raise HTTPException(
            status_code=401,
            detail="Biometric verification failed. Access denied.",
        )


# ── Public accountability ledger ──────────────────────────────────────────────

@router.get("/member/{member_id}")
def member_summary(member_id: str, db: Session = Depends(get_db)):
    """Public summary of a member's accountability record."""
    result = get_actor_history(db, member_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/history/{member_id}")
def member_history(member_id: str, db: Session = Depends(get_db)):
    """Full action history for a member (public ledger)."""
    result = get_actor_history(db, member_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Legal export ──────────────────────────────────────────────────────────────

@router.post("/legal-export")
def legal_export(
    req: LegalExportRequest,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Generate a court-admissible evidence package.
    Requires admin key (law enforcement token in production).
    """
    date_start = (
        datetime.fromisoformat(req.date_start) if req.date_start else None
    )
    date_end = (
        datetime.fromisoformat(req.date_end) if req.date_end else None
    )
    package = export_legal_package(
        db=db,
        member_id=req.member_id,
        date_start=date_start,
        date_end=date_end,
        action_types=req.action_types,
    )
    if "error" in package:
        raise HTTPException(status_code=404, detail=package["error"])
    return package


# ── Revocation ────────────────────────────────────────────────────────────────

@router.post("/revoke/{member_id}")
def revoke(
    member_id: str,
    req: RevokeRequest,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Immediately revoke a member (steward only).
    Triggers revocation cascade: badge invalidated, tokens cancelled,
    federation-wide ban record created.
    """
    try:
        rev = revoke_member(
            db=db,
            member_id=member_id,
            revoked_by=req.revoked_by,
            reason=req.reason,
        )
        return {
            "status": "revoked",
            "event_id": rev.event_id,
            "member_id": member_id,
            "legal_name": rev.legal_name,
            "revoked_at": rev.revoked_at.isoformat(),
            "reason": rev.reason,
            "propagated": rev.propagated,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Duress management (steward only) ─────────────────────────────────────────

@router.get("/duress")
def list_duress_events(
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """List all active (unresolved) duress events."""
    events = (
        db.query(DuressEvent)
        .filter_by(resolved=False)
        .order_by(DuressEvent.triggered_at.desc())
        .all()
    )
    return {
        "active_duress_events": len(events),
        "events": [
            {
                "event_id": e.event_id,
                "member_id": e.member_id,
                "legal_name": e.legal_name,
                "location_node": e.location_node,
                "triggered_at": e.triggered_at.isoformat(),
                "task_id": e.task_id,
                "escrow_until": e.escrow_until.isoformat(),
            }
            for e in events
        ],
    }


@router.post("/duress/{event_id}/resolve")
def resolve_duress(
    event_id: str,
    req: ResolveDuressRequest,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """Resolve a duress escrow event (RELEASED or FROZEN)."""
    if req.resolution not in ("RELEASED", "FROZEN"):
        raise HTTPException(
            status_code=400,
            detail="Resolution must be RELEASED or FROZEN."
        )
    evt = db.query(DuressEvent).filter_by(event_id=event_id).first()
    if not evt:
        raise HTTPException(status_code=404, detail="Duress event not found.")
    if evt.resolved:
        raise HTTPException(status_code=409, detail="Duress event already resolved.")

    evt.resolved = True
    evt.resolved_by = req.resolved_by
    evt.resolution = req.resolution
    db.commit()

    log.info("[DURESS][RESOLVE] Event %s resolved as %s by %s",
             event_id, req.resolution, req.resolved_by)
    return {
        "status": "resolved",
        "event_id": event_id,
        "resolution": req.resolution,
        "resolved_by": req.resolved_by,
    }


# ── Revocation list ───────────────────────────────────────────────────────────

@router.get("/revocations")
def list_revocations(db: Session = Depends(get_db)):
    """
    Public federation revocation list.
    All nodes should check this before accepting cross-node proposals.
    """
    revocations = (
        db.query(RevocationEvent)
        .order_by(RevocationEvent.revoked_at.desc())
        .all()
    )
    return {
        "total": len(revocations),
        "revocations": [
            {
                "event_id": r.event_id,
                "member_id": r.member_id,
                "legal_name": r.legal_name,
                "badge_serial": r.badge_serial,
                "revoked_at": r.revoked_at.isoformat(),
                "reason": r.reason,
                "propagated": r.propagated,
            }
            for r in revocations
        ],
    }


# ── Members list (admin) ──────────────────────────────────────────────────────

@router.get("/members")
def list_members(
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """List all enrolled members (admin only)."""
    members = db.query(ColonyMember).order_by(ColonyMember.enrolled_at.asc()).all()
    return {
        "total": len(members),
        "members": [
            {
                "member_id": m.member_id,
                "legal_name": m.legal_name,
                "role": m.role,
                "badge_serial": m.badge_serial,
                "enrolled_at": m.enrolled_at.isoformat(),
                "suspended": m.suspended,
                "last_seen_node": m.last_seen_node,
                "last_seen_at": m.last_seen_at.isoformat() if m.last_seen_at else None,
                "action_scope": json.loads(m.action_scope),
            }
            for m in members
        ],
    }