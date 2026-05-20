"""
OpenClaw Colony — API Key Authentication
FastAPI dependency that enforces Bearer token auth on protected routes.
"""

import os
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from db import ApiKey, get_db, verify_api_key

# ── Config ────────────────────────────────────────────────────────────────────
# If COLONY_ADMIN_KEY is set in env, it grants admin-level access.
ADMIN_KEY = os.environ.get("COLONY_ADMIN_KEY", "")

# Set COLONY_AUTH_ENABLED=false to disable auth (dev/test mode)
AUTH_ENABLED = os.environ.get("COLONY_AUTH_ENABLED", "true").lower() not in (
    "false", "0", "no", "off"
)

bearer_scheme = HTTPBearer(auto_error=False)


# ── Dependencies ──────────────────────────────────────────────────────────────

def get_current_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[ApiKey]:
    """
    FastAPI dependency.
    - If AUTH_ENABLED=false → always passes (returns None).
    - Otherwise requires a valid Bearer token.
    Raises HTTP 401 on missing/invalid token.
    """
    if not AUTH_ENABLED:
        return None

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token. Include 'Authorization: Bearer <api_key>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_key = credentials.credentials

    # Admin key bypass
    if ADMIN_KEY and raw_key == ADMIN_KEY:
        return None  # admin — no DB row needed

    api_key = verify_api_key(db, raw_key)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return api_key


def require_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> None:
    """
    Stricter dependency for /admin routes.
    Requires COLONY_ADMIN_KEY to be set and matched exactly.
    """
    if not ADMIN_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access not configured. Set COLONY_ADMIN_KEY env var.",
        )

    if credentials is None or credentials.credentials != ADMIN_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin key.",
        )