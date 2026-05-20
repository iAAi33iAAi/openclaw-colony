"""
OpenClaw Colony — Database Layer
SQLite persistence for lineage chain, API keys, and payment records.
"""

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ── Database path ─────────────────────────────────────────────────────────────
DB_PATH = os.environ.get("COLONY_DB_PATH", "colony.db")

# Special handling for :memory: — use shared-cache URI so all connections
# within the same process share the same in-memory database (needed for tests).
if DB_PATH == ":memory:":
    DATABASE_URL = "sqlite:///file::memory:?cache=shared&uri=true"
    _connect_args = {"check_same_thread": False, "uri": True}
else:
    DATABASE_URL = f"sqlite:///{DB_PATH}"
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    echo=False,
)


# Enable WAL mode for concurrent reads (defined after engine)
@event.listens_for(engine, "connect")
def set_wal_mode(dbapi_conn, _):
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA foreign_keys=ON")


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# ── Models ────────────────────────────────────────────────────────────────────

class LineageRecord(Base):
    """Persistent SHA-256 hash chain — one row per APPROVED task."""
    __tablename__ = "lineage"

    id            = Column(Integer, primary_key=True, index=True)
    task_id       = Column(String(36), unique=True, nullable=False, index=True)
    prompt_hash   = Column(String(64), nullable=False)
    lq_composite  = Column(Float, nullable=False)
    lineage_hash  = Column(String(64), nullable=False)
    prev_hash     = Column(String(64), nullable=False)
    committed_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ApiKey(Base):
    """API keys for authenticating /process requests."""
    __tablename__ = "api_keys"

    id            = Column(Integer, primary_key=True, index=True)
    key_id        = Column(String(36), unique=True, nullable=False, index=True)
    key_hash      = Column(String(64), nullable=False)
    label         = Column(String(128), nullable=True)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_used_at  = Column(DateTime, nullable=True)
    stripe_account_id = Column(String(64), nullable=True)


class PaymentRecord(Base):
    """Record of every Stripe MANNA split triggered by an APPROVED task."""
    __tablename__ = "payments"

    id                  = Column(Integer, primary_key=True, index=True)
    task_id             = Column(String(36), nullable=False, index=True)
    lineage_hash        = Column(String(64), nullable=False)
    stripe_transfer_id  = Column(String(128), nullable=True)
    amount_total_cents  = Column(Integer, nullable=False)
    community_cents     = Column(Integer, nullable=False)
    crew_cents          = Column(Integer, nullable=False)
    architect_cents     = Column(Integer, nullable=False)
    currency            = Column(String(8), default="usd")
    status              = Column(String(32), default="pending")
    stripe_error        = Column(Text, nullable=True)
    created_at          = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class WebhookEvent(Base):
    """Idempotency log for Stripe webhook events."""
    __tablename__ = "webhook_events"

    id              = Column(Integer, primary_key=True, index=True)
    stripe_event_id = Column(String(128), unique=True, nullable=False, index=True)
    event_type      = Column(String(64), nullable=False)
    processed_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ── Init ──────────────────────────────────────────────────────────────────────

def init_db():
    """Create all tables. Safe to call multiple times (checkfirst=True)."""
    Base.metadata.create_all(bind=engine, checkfirst=True)


def get_db():
    """FastAPI dependency — yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Lineage helpers ───────────────────────────────────────────────────────────

def get_last_lineage_hash(db: Session) -> str:
    """Return the most recent lineage hash, or 'GENESIS' if chain is empty."""
    row = (
        db.query(LineageRecord)
        .order_by(LineageRecord.id.desc())
        .first()
    )
    return row.lineage_hash if row else "GENESIS"


def append_lineage(
    db: Session,
    task_id: str,
    prompt: str,
    lq_composite: float,
    committed_action: str,
) -> str:
    """Compute next chain link, persist it, return the new hash."""
    prev = get_last_lineage_hash(db)
    payload = f"{prev}:{task_id}:{committed_action}"
    new_hash = hashlib.sha256(payload.encode()).hexdigest()
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

    record = LineageRecord(
        task_id=task_id,
        prompt_hash=prompt_hash,
        lq_composite=lq_composite,
        lineage_hash=new_hash,
        prev_hash=prev,
    )
    db.add(record)
    db.commit()
    return new_hash


# ── API key helpers ───────────────────────────────────────────────────────────

def create_api_key(db: Session, label: str = "", stripe_account_id: str = "") -> dict:
    """Generate a new API key. Returns {'key_id': ..., 'raw_key': ...}."""
    raw_key = "oc_" + secrets.token_urlsafe(32)
    key_id  = str(uuid.uuid4())
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    record = ApiKey(
        key_id=key_id,
        key_hash=key_hash,
        label=label,
        stripe_account_id=stripe_account_id or None,
    )
    db.add(record)
    db.commit()
    return {"key_id": key_id, "raw_key": raw_key}


def verify_api_key(db: Session, raw_key: str) -> Optional[ApiKey]:
    """Return the ApiKey row if valid and active, else None."""
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    row = db.query(ApiKey).filter_by(key_hash=key_hash, is_active=True).first()
    if row:
        row.last_used_at = datetime.now(timezone.utc)
        db.commit()
    return row
