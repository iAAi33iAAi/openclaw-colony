"""
OpenClaw Colony — Federation Layer
Enables sovereign nodes to discover each other, sync lineage chains,
and participate in cross-node governance decisions.

Federation model:
  - Each node is sovereign. No central authority.
  - Nodes announce themselves to known peers on startup.
  - Lineage chain tips are gossiped every SYNC_INTERVAL seconds.
  - Cross-node proposals require a quorum of FEDERATION_QUORUM fraction
    of active peers to approve before the local Aethel gate fires.
  - All federation traffic is authenticated with the node's COLONY_ADMIN_KEY
    (Bearer token) so rogue nodes cannot inject false lineage records.

Environment variables:
  COLONY_NODE_ID          — unique name for this node (e.g. "node-001-bethel")
  COLONY_NODE_URL         — public base URL of this node (e.g. "https://node001.openclaw.net")
  COLONY_PEERS            — comma-separated list of peer base URLs
  FEDERATION_SYNC_INTERVAL— seconds between lineage gossip rounds (default 60)
  FEDERATION_QUORUM       — fraction of active peers required for cross-node
                            approval (default 0.51)
  COLONY_ADMIN_KEY        — shared secret used to authenticate federation calls
"""

import asyncio
import hashlib
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import Session

from db import Base, SessionLocal, engine

log = logging.getLogger("colony.federation")

# ── Config ────────────────────────────────────────────────────────────────────
NODE_ID       = os.environ.get("COLONY_NODE_ID",   "node-001-bethel")
NODE_URL      = os.environ.get("COLONY_NODE_URL",  "http://localhost:8000")
PEERS_RAW     = os.environ.get("COLONY_PEERS",     "")
SYNC_INTERVAL = int(os.environ.get("FEDERATION_SYNC_INTERVAL", "60"))
QUORUM        = float(os.environ.get("FEDERATION_QUORUM", "0.51"))
ADMIN_KEY     = os.environ.get("COLONY_ADMIN_KEY", "")

PEER_URLS: list[str] = [p.strip() for p in PEERS_RAW.split(",") if p.strip()]


# ── Federation DB models ──────────────────────────────────────────────────────

class FederatedNode(Base):
    """Registry of known peer nodes."""
    __tablename__ = "federated_nodes"
    __table_args__ = {"extend_existing": True}

    id           = Column(Integer, primary_key=True, index=True)
    node_id      = Column(String(128), unique=True, nullable=False, index=True)
    base_url     = Column(String(512), nullable=False)
    last_seen    = Column(DateTime, nullable=True)
    last_tip     = Column(String(64), nullable=True)   # latest lineage hash
    active       = Column(Boolean, default=True)
    registered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CrossNodeProposal(Base):
    """A governance proposal that requires multi-node quorum."""
    __tablename__ = "cross_node_proposals"
    __table_args__ = {"extend_existing": True}

    id             = Column(Integer, primary_key=True, index=True)
    proposal_id    = Column(String(36), unique=True, nullable=False, index=True)
    origin_node    = Column(String(128), nullable=False)
    prompt_hash    = Column(String(64),  nullable=False)
    description    = Column(Text,        nullable=False)
    status         = Column(String(32),  default="pending")   # pending/approved/blocked
    votes_for      = Column(Integer,     default=0)
    votes_against  = Column(Integer,     default=0)
    quorum_reached = Column(Boolean,     default=False)
    created_at     = Column(DateTime,    default=lambda: datetime.now(timezone.utc))
    resolved_at    = Column(DateTime,    nullable=True)


class FederationVote(Base):
    """Individual node votes on cross-node proposals."""
    __tablename__ = "federation_votes"
    __table_args__ = {"extend_existing": True}

    id          = Column(Integer, primary_key=True, index=True)
    proposal_id = Column(String(36), nullable=False, index=True)
    voter_node  = Column(String(128), nullable=False)
    vote        = Column(String(8),   nullable=False)   # "approve" / "block"
    lq_score    = Column(String(16),  nullable=True)
    cast_at     = Column(DateTime,    default=lambda: datetime.now(timezone.utc))


def init_federation_tables():
    """Create federation tables (called once on startup)."""
    Base.metadata.create_all(bind=engine, checkfirst=True)
    log.info("Federation tables initialised.")


# ── Node registry helpers ─────────────────────────────────────────────────────

def register_peer(node_id: str, base_url: str, db: Session) -> FederatedNode:
    """Upsert a peer node into the local registry."""
    node = db.query(FederatedNode).filter_by(node_id=node_id).first()
    if node is None:
        node = FederatedNode(node_id=node_id, base_url=base_url)
        db.add(node)
        log.info("Registered new peer: %s @ %s", node_id, base_url)
    else:
        node.base_url  = base_url
        node.active    = True
        node.last_seen = datetime.now(timezone.utc)
    db.commit()
    db.refresh(node)
    return node


def get_active_peers(db: Session) -> list[FederatedNode]:
    return db.query(FederatedNode).filter_by(active=True).all()


def mark_peer_inactive(node_id: str, db: Session):
    node = db.query(FederatedNode).filter_by(node_id=node_id).first()
    if node:
        node.active = False
        db.commit()


# ── Lineage gossip ────────────────────────────────────────────────────────────

@dataclass
class LineageTip:
    node_id:    str
    tip_hash:   str
    tip_index:  int
    timestamp:  str


async def broadcast_lineage_tip(tip_hash: str, tip_index: int, node_state: str = "live"):
    """
    Push our latest lineage tip to all active peers.
    Peers use this to detect if they are behind and need to sync.
    """
    if not PEER_URLS:
        return

    payload = {
        "node_id":    NODE_ID,
        "node_url":   NODE_URL,
        "tip_hash":   tip_hash,
        "tip_index":  tip_index,
        "node_state": node_state,   # Architect Priority: peers know who is SYNCING vs LIVE
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        for peer_url in PEER_URLS:
            try:
                r = await client.post(
                    f"{peer_url}/federation/lineage-tip",
                    json=payload,
                    headers=headers,
                )
                if r.status_code == 200:
                    log.debug("Tip broadcast accepted by %s", peer_url)
                else:
                    log.warning("Tip broadcast rejected by %s: %s", peer_url, r.status_code)
            except Exception as exc:
                log.warning("Tip broadcast failed for %s: %s", peer_url, exc)


async def fetch_lineage_records(peer_url: str, since_hash: str) -> list[dict]:
    """
    Pull lineage records from a peer that are newer than since_hash.
    Returns a list of serialised LineageRecord dicts.
    """
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"{peer_url}/federation/lineage",
                params={"since_hash": since_hash},
                headers=headers,
            )
            if r.status_code == 200:
                return r.json().get("records", [])
            log.warning("Lineage fetch from %s returned %s", peer_url, r.status_code)
    except Exception as exc:
        log.warning("Lineage fetch failed for %s: %s", peer_url, exc)
    return []


# ── Cross-node proposal helpers ───────────────────────────────────────────────

def create_proposal(description: str, prompt_hash: str, db: Session) -> CrossNodeProposal:
    proposal = CrossNodeProposal(
        proposal_id  = str(uuid.uuid4()),
        origin_node  = NODE_ID,
        prompt_hash  = prompt_hash,
        description  = description,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    log.info("Created cross-node proposal %s", proposal.proposal_id)
    return proposal


def record_vote(
    proposal_id: str,
    voter_node:  str,
    vote:        str,          # "approve" or "block"
    lq_score:    Optional[str],
    db:          Session,
) -> CrossNodeProposal:
    """Record a vote and recompute quorum status."""
    # Idempotency — one vote per node per proposal
    existing = db.query(FederationVote).filter_by(
        proposal_id=proposal_id, voter_node=voter_node
    ).first()
    if existing:
        log.debug("Duplicate vote from %s on %s — ignored", voter_node, proposal_id)
        return db.query(CrossNodeProposal).filter_by(proposal_id=proposal_id).first()

    fv = FederationVote(
        proposal_id=proposal_id,
        voter_node=voter_node,
        vote=vote,
        lq_score=lq_score,
    )
    db.add(fv)

    proposal = db.query(CrossNodeProposal).filter_by(proposal_id=proposal_id).first()
    if proposal and proposal.status == "pending":
        if vote == "approve":
            proposal.votes_for     += 1
        else:
            proposal.votes_against += 1

        active_peers = db.query(FederatedNode).filter_by(active=True).count()
        total_votes  = proposal.votes_for + proposal.votes_against
        quorum_n     = max(1, int(active_peers * QUORUM))

        if proposal.votes_for >= quorum_n:
            proposal.status        = "approved"
            proposal.quorum_reached = True
            proposal.resolved_at   = datetime.now(timezone.utc)
            log.info("Proposal %s APPROVED (votes_for=%d, quorum=%d)",
                     proposal_id, proposal.votes_for, quorum_n)
        elif proposal.votes_against > (active_peers - quorum_n):
            proposal.status        = "blocked"
            proposal.quorum_reached = True
            proposal.resolved_at   = datetime.now(timezone.utc)
            log.info("Proposal %s BLOCKED (votes_against=%d)",
                     proposal_id, proposal.votes_against)

    db.commit()
    db.refresh(proposal)
    return proposal


async def broadcast_proposal(proposal: CrossNodeProposal):
    """Send a new cross-node proposal to all active peers for voting."""
    if not PEER_URLS:
        return

    payload = {
        "proposal_id":  proposal.proposal_id,
        "origin_node":  proposal.origin_node,
        "prompt_hash":  proposal.prompt_hash,
        "description":  proposal.description,
        "created_at":   proposal.created_at.isoformat(),
    }
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        for peer_url in PEER_URLS:
            try:
                r = await client.post(
                    f"{peer_url}/federation/proposals",
                    json=payload,
                    headers=headers,
                )
                log.debug("Proposal broadcast to %s: %s", peer_url, r.status_code)
            except Exception as exc:
                log.warning("Proposal broadcast failed for %s: %s", peer_url, exc)


async def cast_vote_on_peers(proposal_id: str, vote: str, lq_score: float):
    """Send our vote on a proposal to all active peers."""
    if not PEER_URLS:
        return

    payload = {
        "proposal_id": proposal_id,
        "voter_node":  NODE_ID,
        "vote":        vote,
        "lq_score":    str(round(lq_score, 4)),
    }
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        for peer_url in PEER_URLS:
            try:
                r = await client.post(
                    f"{peer_url}/federation/votes",
                    json=payload,
                    headers=headers,
                )
                log.debug("Vote cast on %s: %s", peer_url, r.status_code)
            except Exception as exc:
                log.warning("Vote cast failed for %s: %s", peer_url, exc)


# ── Periodic sync task ────────────────────────────────────────────────────────

async def announce_self():
    """POST our node identity to all configured peers."""
    if not PEER_URLS:
        log.info("No peers configured — running as standalone node.")
        return

    payload = {
        "node_id":  NODE_ID,
        "node_url": NODE_URL,
    }
    headers = {"Authorization": f"Bearer {ADMIN_KEY}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        for peer_url in PEER_URLS:
            try:
                r = await client.post(
                    f"{peer_url}/federation/announce",
                    json=payload,
                    headers=headers,
                )
                if r.status_code == 200:
                    log.info("Announced to peer %s", peer_url)
                else:
                    log.warning("Announce rejected by %s: %s", peer_url, r.status_code)
            except Exception as exc:
                log.warning("Announce failed for %s: %s", peer_url, exc)


async def federation_sync_loop():
    """
    Background task: runs every SYNC_INTERVAL seconds.
    1. Announces self to all peers.
    2. Fetches and logs their latest lineage tips.
    3. Drives NodeStateMachine transitions based on peer responses.
    4. Checks for isolation (no peer contact beyond timeout).
    """
    log.info("Federation sync loop started (interval=%ds, peers=%d)",
             SYNC_INTERVAL, len(PEER_URLS))

    # Import state machine — initialised by main.py on startup
    try:
        from state_machine import get_node_state_machine, NodeState
        _sm_available = True
    except Exception:
        _sm_available = False
        log.warning("State machine not available — sync loop running without SM.")

    while True:
        try:
            await announce_self()

            # After announcing, attempt ANNOUNCING → SYNCING if peers responded
            if _sm_available:
                sm = get_node_state_machine()
                if sm.state == NodeState.ANNOUNCING and sm.highest_peer_tip >= 0:
                    sm.transition(NodeState.SYNCING, "Peer responded to announce")

                # Check if our tip has caught up — attempt SYNCING → LIVE
                if sm.state == NodeState.SYNCING:
                    # update_our_tip is called by the /process endpoint after each commit
                    # Here we just attempt the transition — SM guards with lineage head check
                    promoted = sm.transition(
                        NodeState.LIVE,
                        f"Lineage tip check: our={sm.our_tip} peer_max={sm.highest_peer_tip}"
                    )
                    if promoted:
                        log.info("[FEDERATION] Node promoted to LIVE (tip=%d)", sm.our_tip)

                # Check for isolation
                sm.check_isolation()

        except Exception as exc:
            log.error("Federation sync error: %s", exc)

        await asyncio.sleep(SYNC_INTERVAL)