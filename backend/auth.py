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
def _admin_key() -> str:
    return os.environ.get("COLONY_ADMIN_KEY", "").strip()


def _auth_enabled() -> bool:
    return os.environ.get("COLONY_AUTH_ENABLED", "true").lower() not in (
        "false", "0", "no", "off"
    )


def _production_mode() -> bool:
    return os.environ.get("COLONY_ENV", "").lower() == "production"

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
    if not _auth_enabled():
        if _production_mode():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication cannot be disabled in production.",
            )
        return None

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token. Include 'Authorization: Bearer <api_key>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_key = credentials.credentials

    # Admin key bypass
    admin_key = _admin_key()
    if admin_key and raw_key == admin_key:
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
    admin_key = _admin_key()
    if not admin_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access not configured. Set COLONY_ADMIN_KEY env var.",
        )

    if credentials is None or credentials.credentials != admin_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin key.",
        )