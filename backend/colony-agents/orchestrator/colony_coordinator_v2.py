"""
OpenClaw Colony — Colony Coordinator v2
Adds: persistent lineage, API key auth, rate limiting, Stripe MANNA bridge.
Drop-in replacement for colony_coordinator.py
"""

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

from love_quality.love_quality_engine import LoveQualityEngine, LQScore
from aethel_interface import AethelInterface

# ── Agent imports ─────────────────────────────────────────────────────────────
from colony_agents.strategic_agent   import StrategicAgent
from colony_agents.technical_agent   import TechnicalAgent
from colony_agents.resources_agent   import ResourcesAgent
from colony_agents.comms_agent       import CommsAgent
from colony_agents.analysis_agent    import AnalysisAgent
from colony_agents.quality_agent     import QualityAgent
from colony_agents.innovation_agent  import InnovationAgent

# ── New infrastructure ────────────────────────────────────────────────────────
from db import (
    init_db, get_db, append_lineage,
    create_api_key, PaymentRecord, SessionLocal,
)
from auth import get_current_key, require_admin
from rate_limit import limiter, RATE_PROCESS, RATE_ADMIN, RATE_WEBHOOK
from stripe_bridge import process_manna_payment, MOCK_MODE
from federation import (
    init_federation_tables, federation_sync_loop,
    NODE_ID, NODE_URL, PEER_URLS,
)
from federation_routes import router as federation_router
from biometric import init_biometric_tables, record_accountability
from biometric_routes import router as biometric_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("colony.coordinator")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ColonyTask:
    task_id:          str  = field(default_factory=lambda: str(uuid.uuid4()))
    prompt:           str  = ""
    submitted_at:     str  = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    human_consent:    bool = True
    biometric_token:  Optional[dict] = None   # Gate 0 attestation token
    action_type:      str  = "proposal"       # scope verified against token


@dataclass
class ColonyResult:
    task_id:          str
    prompt:           str
    agent_outputs:    dict[str, Any]
    lq_score:         dict
    aethel_verdict:   str
    aethel_gates:     dict
    committed_action: Optional[str]
    lineage_hash:     Optional[str]
    payment:          Optional[dict]
    timestamp:        str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ── Coordinator ───────────────────────────────────────────────────────────────

class ColonyCoordinator:
    """Orchestrates the full 7-agent → LQ → Aethel → Stripe pipeline."""

    AGENTS = [
        StrategicAgent, TechnicalAgent, ResourcesAgent, CommsAgent,
        AnalysisAgent, QualityAgent, InnovationAgent,
    ]

    def __init__(self):
        self.lq_engine = LoveQualityEngine()
        self.aethel    = AethelInterface()
        self.agents    = [cls() for cls in self.AGENTS]

    async def start(self):
        log.info("Initialising OpenClaw Colony v2 …")
        init_db()
        init_federation_tables()
        init_biometric_tables()
        log.info("[DB] SQLite lineage store ready.")
        for agent in self.agents:
            await agent.initialize()
            log.info("[AGENT READY] %s", agent.name)
        log.info("[AETHEL] Kernel online. Gates: 4/4 active (Gate 0: Biometric).")
        log.info("[STRIPE] Mock mode: %s", MOCK_MODE)
        log.info("[FEDERATION] Node ID: %s  Peers: %d", NODE_ID, len(PEER_URLS))

    async def process(self, task: ColonyTask) -> ColonyResult:
        log.info("Processing task %s: %r", task.task_id, task.prompt[:80])

        # 1 — Parallel agent evaluation
        agent_outputs = await self._run_agents(task)

        # 2 — Love Quality scoring
        lq: LQScore = self.lq_engine.score(task.prompt, agent_outputs)
        log.info(
            "LQ composite=%.3f  threshold=0.85  pass=%s",
            lq.composite, lq.composite >= 0.85,
        )

        # 3 — Aethel kernel gates (Gate 0 biometric + Gates 1-3)
        db_session = SessionLocal()
        try:
            aethel_result = self.aethel.validate(
                task_id=task.task_id,
                human_consent=task.human_consent,
                lq_score=lq.composite,
                agent_outputs=agent_outputs,
                biometric_token=task.biometric_token,
                action_type=task.action_type,
                db=db_session,
            )

            # Record accountability entry regardless of verdict
            if task.biometric_token:
                record_accountability(
                    db=db_session,
                    token=task.biometric_token,
                    action_type=task.action_type,
                    task_id=task.task_id,
                    lineage_hash=None,   # updated below if APPROVED
                    outcome=aethel_result["verdict"],
                )
        finally:
            db_session.close()

        committed_action = None
        lineage_hash     = None
        payment_info     = None

        if aethel_result["verdict"] == "APPROVED":
            committed_action = self._build_action(task, agent_outputs, lq)

            # 4 — Persist lineage to SQLite
            db = SessionLocal()
            try:
                lineage_hash = append_lineage(
                    db,
                    task_id=task.task_id,
                    prompt=task.prompt,
                    lq_composite=lq.composite,
                    committed_action=committed_action,
                )
            finally:
                db.close()

            log.info("[APPROVED] Lineage hash: %s", lineage_hash)

            # 5 — Stripe MANNA split
            payment = process_manna_payment(task.task_id, lineage_hash)
            payment_info = payment.as_dict()

            # 6 — Persist payment record
            db = SessionLocal()
            try:
                rec = PaymentRecord(
                    task_id=task.task_id,
                    lineage_hash=lineage_hash,
                    stripe_transfer_id=payment.community_id,  # primary ref
                    amount_total_cents=payment.split.total_cents,
                    community_cents=payment.split.community_cents,
                    crew_cents=payment.split.crew_cents,
                    architect_cents=payment.split.architect_cents,
                    status=payment.status,
                    stripe_error=payment.error,
                )
                db.add(rec)
                db.commit()
            finally:
                db.close()

            log.info(
                "[MANNA] status=%s  community=%d  crew=%d  architect=%d cents",
                payment.status,
                payment.split.community_cents,
                payment.split.crew_cents,
                payment.split.architect_cents,
            )
        else:
            log.warning(
                "[BLOCKED] Task %s blocked at gate %s — %s",
                task.task_id,
                aethel_result.get("blocked_at_gate"),
                aethel_result.get("reason"),
            )

        return ColonyResult(
            task_id=task.task_id,
            prompt=task.prompt,
            agent_outputs=agent_outputs,
            lq_score=asdict(lq),
            aethel_verdict=aethel_result["verdict"],
            aethel_gates=aethel_result["gates"],
            committed_action=committed_action,
            lineage_hash=lineage_hash,
            payment=payment_info,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _run_agents(self, task: ColonyTask) -> dict[str, Any]:
        coros   = [agent.evaluate(task.prompt) for agent in self.agents]
        results = await asyncio.gather(*coros, return_exceptions=True)
        outputs: dict[str, Any] = {}
        for agent, result in zip(self.agents, results):
            if isinstance(result, Exception):
                log.error("Agent %s raised: %s", agent.name, result)
                outputs[agent.name] = {"error": str(result)}
            else:
                outputs[agent.name] = result
        return outputs

    def _build_action(self, task, agent_outputs, lq) -> str:
        return json.dumps(
            {
                "task_id":      task.task_id,
                "prompt":       task.prompt,
                "lq_composite": lq.composite,
                "summary": {
                    name: out.get("summary", "") if isinstance(out, dict) else str(out)
                    for name, out in agent_outputs.items()
                },
            },
            indent=2,
        )


# ── FastAPI application ───────────────────────────────────────────────────────

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.orm import Session

from db import (
    ApiKey, LineageRecord, PaymentRecord as PaymentRecordModel,
    WebhookEvent, get_db, create_api_key as db_create_api_key,
)
from stripe_bridge import (
    verify_webhook, calculate_manna_split, MANNA_CENTS,
    STRIPE_COMMUNITY_ACCOUNT, STRIPE_CREW_ACCOUNT, STRIPE_ARCHITECT_ACCOUNT,
)

app = FastAPI(title="OpenClaw Colony API", version="0.7.0")

# Rate limiting
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

coordinator: Optional[ColonyCoordinator] = None


@app.on_event("startup")
async def startup():
    global coordinator
    coordinator = ColonyCoordinator()
    await coordinator.start()
    # Start federation background sync loop
    asyncio.create_task(federation_sync_loop())
    log.info("[FEDERATION] Sync loop started.")

# Mount federation + biometric routes
app.include_router(federation_router)
app.include_router(biometric_router)


# ── Request / Response models ─────────────────────────────────────────────────

class TaskRequest(BaseModel):
    prompt:           str
    human_consent:    bool = True
    biometric_token:  Optional[dict] = None   # Gate 0 attestation token
    action_type:      str  = "proposal"


class TaskResponse(BaseModel):
    task_id:          str
    prompt:           str
    lq_score:         dict
    aethel_verdict:   str
    aethel_gates:     dict
    committed_action: Optional[str]
    lineage_hash:     Optional[str]
    payment:          Optional[dict]
    timestamp:        str


class CreateKeyRequest(BaseModel):
    label:             str = ""
    stripe_account_id: str = ""


class CreateKeyResponse(BaseModel):
    key_id:  str
    raw_key: str
    label:   str
    note:    str = "Store this key securely — it will not be shown again."


# ── Core endpoint ─────────────────────────────────────────────────────────────

@app.post("/process", response_model=TaskResponse)
@limiter.limit(RATE_PROCESS)
async def process_task(
    request: Request,
    req: TaskRequest,
    api_key: Optional[ApiKey] = Depends(get_current_key),
):
    if not coordinator:
        raise HTTPException(status_code=503, detail="Colony not initialised")
    task   = ColonyTask(
        prompt=req.prompt,
        human_consent=req.human_consent,
        biometric_token=req.biometric_token,
        action_type=req.action_type,
    )
    result = await coordinator.process(task)
    return TaskResponse(
        task_id=result.task_id,
        prompt=result.prompt,
        lq_score=result.lq_score,
        aethel_verdict=result.aethel_verdict,
        aethel_gates=result.aethel_gates,
        committed_action=result.committed_action,
        lineage_hash=result.lineage_hash,
        payment=result.payment,
        timestamp=result.timestamp,
    )


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    db = SessionLocal()
    try:
        from federation import FederatedNode
        active_peers  = db.query(FederatedNode).filter_by(active=True).count()
        total_peers   = db.query(FederatedNode).count()
    except Exception:
        active_peers  = 0
        total_peers   = 0
    finally:
        db.close()

    return {
        "status":      "ok",
        "colony":      "online",
        "gates":       "4/4 active (Gate 0: Biometric)",
        "stripe_mode": "mock" if MOCK_MODE else "live",
        "version":     "0.7.0",
        "federation": {
            "node_id":      NODE_ID,
            "node_url":     NODE_URL,
            "active_peers": active_peers,
            "total_peers":  total_peers,
        },
        "biometric": {
            "required":    __import__('os').environ.get("COLONY_BIOMETRIC_REQUIRED", "true"),
            "ttl_seconds": int(__import__('os').environ.get("COLONY_ATTESTATION_TTL", "90")),
        },
    }


# ── Stripe webhook ────────────────────────────────────────────────────────────

@app.post("/webhook/stripe")
@limiter.limit(RATE_WEBHOOK)
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Receives Stripe webhook events.
    Verifies signature, deduplicates via WebhookEvent table,
    and updates PaymentRecord status on transfer.paid / transfer.failed.
    """
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    event = verify_webhook(payload, sig_header)
    if event is None:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_id   = event.get("id", "")
    event_type = event.get("type", "")

    # Idempotency check
    existing = db.query(WebhookEvent).filter_by(stripe_event_id=event_id).first()
    if existing:
        return {"status": "already_processed"}

    # Record event
    db.add(WebhookEvent(stripe_event_id=event_id, event_type=event_type))
    db.commit()

    # Handle transfer events
    if event_type in ("transfer.paid", "transfer.reversed", "transfer.failed"):
        transfer    = event.get("data", {}).get("object", {})
        transfer_id = transfer.get("id", "")
        metadata    = transfer.get("metadata", {})
        task_id     = metadata.get("task_id", "")

        if task_id:
            rec = db.query(PaymentRecordModel).filter_by(task_id=task_id).first()
            if rec:
                rec.status = "completed" if event_type == "transfer.paid" else "failed"
                db.commit()
                log.info("[WEBHOOK] %s → task %s status=%s", event_type, task_id, rec.status)

    return {"status": "ok", "event_type": event_type}


# ── Admin endpoints ───────────────────────────────────────────────────────────

@app.post("/admin/keys", response_model=CreateKeyResponse)
@limiter.limit(RATE_ADMIN)
async def admin_create_key(
    request: Request,
    req: CreateKeyRequest,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create a new API key. Requires COLONY_ADMIN_KEY header."""
    result = db_create_api_key(db, label=req.label, stripe_account_id=req.stripe_account_id)
    return CreateKeyResponse(
        key_id=result["key_id"],
        raw_key=result["raw_key"],
        label=req.label,
    )


@app.get("/admin/keys")
@limiter.limit(RATE_ADMIN)
async def admin_list_keys(
    request: Request,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all API keys (hashes only — raw keys are never stored)."""
    keys = db.query(ApiKey).all()
    return [
        {
            "key_id":             k.key_id,
            "label":              k.label,
            "is_active":          k.is_active,
            "created_at":         k.created_at.isoformat() if k.created_at else None,
            "last_used_at":       k.last_used_at.isoformat() if k.last_used_at else None,
            "stripe_account_id":  k.stripe_account_id,
        }
        for k in keys
    ]


@app.delete("/admin/keys/{key_id}")
@limiter.limit(RATE_ADMIN)
async def admin_revoke_key(
    request: Request,
    key_id: str,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Revoke an API key by key_id."""
    key = db.query(ApiKey).filter_by(key_id=key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    key.is_active = False
    db.commit()
    return {"status": "revoked", "key_id": key_id}


@app.get("/admin/lineage")
@limiter.limit(RATE_ADMIN)
async def admin_lineage(
    request: Request,
    limit: int = 50,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return the most recent lineage records (newest first)."""
    records = (
        db.query(LineageRecord)
        .order_by(LineageRecord.id.desc())
        .limit(min(limit, 500))
        .all()
    )
    return [
        {
            "id":            r.id,
            "task_id":       r.task_id,
            "prompt_hash":   r.prompt_hash,
            "lq_composite":  r.lq_composite,
            "lineage_hash":  r.lineage_hash,
            "prev_hash":     r.prev_hash,
            "committed_at":  r.committed_at.isoformat() if r.committed_at else None,
        }
        for r in records
    ]


@app.get("/admin/payments")
@limiter.limit(RATE_ADMIN)
async def admin_payments(
    request: Request,
    limit: int = 50,
    _: None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return the most recent payment records (newest first)."""
    records = (
        db.query(PaymentRecordModel)
        .order_by(PaymentRecordModel.id.desc())
        .limit(min(limit, 500))
        .all()
    )
    return [
        {
            "id":                 r.id,
            "task_id":            r.task_id,
            "lineage_hash":       r.lineage_hash,
            "stripe_transfer_id": r.stripe_transfer_id,
            "amount_total_cents": r.amount_total_cents,
            "community_cents":    r.community_cents,
            "crew_cents":         r.crew_cents,
            "architect_cents":    r.architect_cents,
            "currency":           r.currency,
            "status":             r.status,
            "stripe_error":       r.stripe_error,
            "created_at":         r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


@app.get("/admin/manna/config")
@limiter.limit(RATE_ADMIN)
async def admin_manna_config(
    request: Request,
    _: None = Depends(require_admin),
):
    """Show current MANNA split configuration."""
    split = calculate_manna_split(MANNA_CENTS)
    return {
        "manna_cents_per_task": MANNA_CENTS,
        "split": split.as_dict(),
        "percentages": {"community": "84%", "crew": "15%", "architect": "1%"},
        "stripe_mode": "mock" if MOCK_MODE else "live",
        "community_account": STRIPE_COMMUNITY_ACCOUNT or "not set",
        "crew_account":      STRIPE_CREW_ACCOUNT or "not set",
        "architect_account": STRIPE_ARCHITECT_ACCOUNT or "not set",
    }


# ── Rate limit error handler ──────────────────────────────────────────────────

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return Response(
        content='{"detail":"Rate limit exceeded. Slow down."}',
        status_code=429,
        media_type="application/json",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "colony_coordinator_v2:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )