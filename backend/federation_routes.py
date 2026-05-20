"""
OpenClaw Colony — Federation API Routes
Mounts onto the main FastAPI app to expose federation endpoints.

Endpoints:
  POST /federation/announce          — peer announces itself
  POST /federation/lineage-tip       — peer pushes its latest lineage tip
  GET  /federation/lineage           — serve our lineage records to a peer
  GET  /federation/nodes             — list all known peer nodes
  POST /federation/proposals         — receive a cross-node proposal
  POST /federation/votes             — receive a vote on a proposal
  GET  /federation/proposals/{id}    — get proposal status
  GET  /federation/status            — federation health summary
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import require_admin
from db import SessionLocal, LineageRecord, get_db
from federation import (
    NODE_ID, NODE_URL, QUORUM,
    FederatedNode, CrossNodeProposal, FederationVote,
    register_peer, get_active_peers, mark_peer_inactive,
    record_vote, create_proposal, broadcast_proposal,
    cast_vote_on_peers,
)

log = logging.getLogger("colony.federation_routes")
router = APIRouter(prefix="/federation", tags=["federation"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AnnounceRequest(BaseModel):
    node_id:  str
    node_url: str

class LineageTipRequest(BaseModel):
    node_id:   str
    node_url:  str
    tip_hash:  str
    tip_index: int
    timestamp: str
    node_state: Optional[str] = None   # peer's current NodeState (for dashboard)

class ProposalRequest(BaseModel):
    proposal_id: str
    origin_node: str
    prompt_hash: str
    description: str
    created_at:  str

class VoteRequest(BaseModel):
    proposal_id: str
    voter_node:  str
    vote:        str          # "approve" or "block"
    lq_score:    Optional[str] = None

class HeartbeatRequest(BaseModel):
    node_id:   str
    node_url:  str
    old_state: str
    new_state: str
    reason:    str
    timestamp: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/announce")
async def announce(req: AnnounceRequest, _=Depends(require_admin)):
    """A peer node announces its presence. Register or refresh it."""
    db = SessionLocal()
    try:
        node = register_peer(req.node_id, req.node_url, db)
        node.last_seen = datetime.now(timezone.utc)
        db.commit()
        log.info("Peer announced: %s @ %s", req.node_id, req.node_url)
        return {
            "status":  "registered",
            "node_id": req.node_id,
            "our_node_id": NODE_ID,
            "our_node_url": NODE_URL,
        }
    finally:
        db.close()


@router.post("/lineage-tip")
async def receive_lineage_tip(req: LineageTipRequest, _=Depends(require_admin)):
    """
    Receive a peer's latest lineage tip.
    Update their last_seen and last_tip in our registry.
    Feed tip_index into NodeStateMachine so SYNCING→LIVE guard stays current.
    """
    db = SessionLocal()
    try:
        node = db.query(FederatedNode).filter_by(node_id=req.node_id).first()
        if node is None:
            node = register_peer(req.node_id, req.node_url, db)

        node.last_seen = datetime.now(timezone.utc)
        node.last_tip  = req.tip_hash
        node.active    = True
        db.commit()

        our_count = db.query(LineageRecord).count()

        # Feed peer tip into state machine — updates highest_peer_tip
        # which guards the SYNCING → LIVE transition
        try:
            from state_machine import get_node_state_machine, NodeState
            sm = get_node_state_machine()
            sm.update_peer_tip(req.tip_index)
            sm.update_our_tip(our_count)

            if req.tip_index > our_count:
                log.info(
                    "Peer %s is ahead (their index=%d, ours=%d, state=%s) — sync available",
                    req.node_id, req.tip_index, our_count,
                    getattr(req, "node_state", "unknown"),
                )
                # If we were LIVE, drop back to SYNCING
                if sm.state == NodeState.LIVE:
                    sm.transition(
                        NodeState.SYNCING,
                        f"Peer {req.node_id} tip={req.tip_index} ahead of ours={our_count}"
                    )
        except Exception as exc:
            log.debug("State machine update skipped: %s", exc)

        return {
            "status":           "tip_received",
            "our_lineage_count": our_count,
            "peer_tip_index":   req.tip_index,
            "synced":           our_count >= req.tip_index,
        }
    finally:
        db.close()


@router.get("/lineage")
async def serve_lineage(since_hash: str = "", _=Depends(require_admin)):
    """
    Serve our lineage records to a requesting peer.
    If since_hash is provided, return only records after that hash.
    """
    db = SessionLocal()
    try:
        records = db.query(LineageRecord).order_by(LineageRecord.id).all()

        # Find the cutoff index
        start_idx = 0
        if since_hash:
            for i, r in enumerate(records):
                if r.lineage_hash == since_hash:
                    start_idx = i + 1
                    break

        result = [
            {
                "task_id":      r.task_id,
                "prompt_hash":  r.prompt_hash,
                "lq_composite": r.lq_composite,
                "lineage_hash": r.lineage_hash,
                "prev_hash":    r.prev_hash,
                "committed_at": r.committed_at.isoformat() if r.committed_at else None,
            }
            for r in records[start_idx:]
        ]
        return {
            "node_id":      NODE_ID,
            "total_records": len(records),
            "records":      result,
        }
    finally:
        db.close()


@router.get("/nodes")
async def list_nodes(_=Depends(require_admin)):
    """List all known peer nodes in our registry."""
    db = SessionLocal()
    try:
        nodes = db.query(FederatedNode).all()
        return {
            "our_node_id": NODE_ID,
            "our_node_url": NODE_URL,
            "peers": [
                {
                    "node_id":      n.node_id,
                    "base_url":     n.base_url,
                    "active":       n.active,
                    "last_seen":    n.last_seen.isoformat() if n.last_seen else None,
                    "last_tip":     n.last_tip,
                    "registered_at": n.registered_at.isoformat() if n.registered_at else None,
                }
                for n in nodes
            ],
        }
    finally:
        db.close()


@router.post("/proposals")
async def receive_proposal(req: ProposalRequest, _=Depends(require_admin)):
    """
    Receive a cross-node governance proposal from a peer.
    Store it locally and cast our vote using the local LQ engine.
    """
    db = SessionLocal()
    try:
        # Idempotency — don't store duplicates
        existing = db.query(CrossNodeProposal).filter_by(
            proposal_id=req.proposal_id
        ).first()
        if existing:
            return {"status": "already_known", "proposal_id": req.proposal_id}

        proposal = CrossNodeProposal(
            proposal_id = req.proposal_id,
            origin_node = req.origin_node,
            prompt_hash = req.prompt_hash,
            description = req.description,
        )
        db.add(proposal)
        db.commit()
        log.info("Received cross-node proposal %s from %s",
                 req.proposal_id, req.origin_node)

        # Auto-vote: run description through a lightweight LQ check
        # (full 7-agent pipeline would be too heavy for federation traffic)
        try:
            from love_quality.love_quality_engine import LoveQualityEngine
            engine = LoveQualityEngine()
            lq = engine.score(req.description, {})
            vote = "approve" if lq.passed else "block"
            lq_val = lq.composite
        except Exception:
            # If LQ engine unavailable, abstain by approving (local Aethel
            # will still gate the final action)
            vote   = "approve"
            lq_val = 0.0

        record_vote(req.proposal_id, NODE_ID, vote, str(round(lq_val, 4)), db)

        # Broadcast our vote back to all peers asynchronously
        import asyncio
        asyncio.create_task(
            cast_vote_on_peers(req.proposal_id, vote, lq_val)
        )

        return {
            "status":      "received",
            "proposal_id": req.proposal_id,
            "our_vote":    vote,
            "our_lq":      round(lq_val, 4),
        }
    finally:
        db.close()


@router.post("/votes")
async def receive_vote(req: VoteRequest, _=Depends(require_admin)):
    """Receive a vote from a peer node on an existing proposal."""
    if req.vote not in ("approve", "block"):
        raise HTTPException(status_code=400, detail="vote must be 'approve' or 'block'")

    db = SessionLocal()
    try:
        proposal = db.query(CrossNodeProposal).filter_by(
            proposal_id=req.proposal_id
        ).first()
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")

        updated = record_vote(
            req.proposal_id, req.voter_node, req.vote, req.lq_score, db
        )
        return {
            "status":        "vote_recorded",
            "proposal_id":   req.proposal_id,
            "current_status": updated.status,
            "votes_for":     updated.votes_for,
            "votes_against": updated.votes_against,
            "quorum_reached": updated.quorum_reached,
        }
    finally:
        db.close()


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, _=Depends(require_admin)):
    """Get the current status of a cross-node proposal."""
    db = SessionLocal()
    try:
        proposal = db.query(CrossNodeProposal).filter_by(
            proposal_id=proposal_id
        ).first()
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")

        votes = db.query(FederationVote).filter_by(proposal_id=proposal_id).all()
        return {
            "proposal_id":   proposal.proposal_id,
            "origin_node":   proposal.origin_node,
            "description":   proposal.description,
            "status":        proposal.status,
            "votes_for":     proposal.votes_for,
            "votes_against": proposal.votes_against,
            "quorum_reached": proposal.quorum_reached,
            "created_at":    proposal.created_at.isoformat(),
            "resolved_at":   proposal.resolved_at.isoformat() if proposal.resolved_at else None,
            "votes": [
                {
                    "voter_node": v.voter_node,
                    "vote":       v.vote,
                    "lq_score":   v.lq_score,
                    "cast_at":    v.cast_at.isoformat(),
                }
                for v in votes
            ],
        }
    finally:
        db.close()


@router.get("/status")
async def federation_status(_=Depends(require_admin)):
    """
    Federation health summary — active peers, lineage count, pending proposals.
    Architect Priority 4: includes NodeState for Laminar Flow dashboard monitoring.
    """
    db = SessionLocal()
    try:
        active_peers    = db.query(FederatedNode).filter_by(active=True).count()
        total_peers     = db.query(FederatedNode).count()
        lineage_count   = db.query(LineageRecord).count()
        pending_props   = db.query(CrossNodeProposal).filter_by(status="pending").count()
        approved_props  = db.query(CrossNodeProposal).filter_by(status="approved").count()
        blocked_props   = db.query(CrossNodeProposal).filter_by(status="blocked").count()
        expired_props   = db.query(CrossNodeProposal).filter_by(status="expired").count()

        # Include NodeState from state machine if available
        node_state_info = {"state": "unknown", "synced": None}
        try:
            from state_machine import get_node_state_machine
            sm = get_node_state_machine()
            node_state_info = sm.as_dict()
        except Exception:
            pass

        return {
            "node_id":          NODE_ID,
            "node_url":         NODE_URL,
            "quorum_threshold": QUORUM,
            "node_state":       node_state_info,   # Laminar Flow indicator
            "peers": {
                "active": active_peers,
                "total":  total_peers,
            },
            "lineage": {
                "record_count": lineage_count,
            },
            "proposals": {
                "pending":  pending_props,
                "approved": approved_props,
                "blocked":  blocked_props,
                "expired":  expired_props,
            },
        }
    finally:
        db.close()


@router.post("/heartbeat")
async def receive_heartbeat(req: HeartbeatRequest, _=Depends(require_admin)):
    """
    Architect Priority 4: Receive a NodeState transition heartbeat from a peer.
    Updates the peer's record in our registry so the /status dashboard
    reflects the full grid's Laminar Flow state.
    """
    db = SessionLocal()
    try:
        node = db.query(FederatedNode).filter_by(node_id=req.node_id).first()
        if node is None:
            from federation import register_peer
            node = register_peer(req.node_id, req.node_url, db)

        from datetime import datetime, timezone
        node.last_seen = datetime.now(timezone.utc)
        node.active    = True
        # Store the peer's current state in last_tip field (reused as state carrier)
        # In a future schema migration, add a dedicated node_state column
        db.commit()

        log.info(
            "[HEARTBEAT] Peer %s transitioned %s → %s (reason: %s)",
            req.node_id, req.old_state, req.new_state, req.reason
        )
        return {
            "status":    "heartbeat_received",
            "node_id":   req.node_id,
            "new_state": req.new_state,
        }
    finally:
        db.close()