"""
OpenClaw Colony — Rate Limiting
Per-API-key and per-IP sliding window rate limits using slowapi.
"""

import os
from typing import Optional

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

# ── Config ────────────────────────────────────────────────────────────────────
# Override via env vars:
#   COLONY_RATE_PROCESS   = "30/minute"   (default)
#   COLONY_RATE_ADMIN     = "60/minute"   (default)
#   COLONY_RATE_WEBHOOK   = "120/minute"  (default)

RATE_PROCESS = os.environ.get("COLONY_RATE_PROCESS", "30/minute")
RATE_ADMIN   = os.environ.get("COLONY_RATE_ADMIN",   "60/minute")
RATE_WEBHOOK = os.environ.get("COLONY_RATE_WEBHOOK", "120/minute")


def _key_func(request: Request) -> str:
    """
    Rate-limit key: use API key ID if present in Authorization header,
    otherwise fall back to remote IP address.
    This ensures per-key limits rather than per-IP (which would penalise
    shared NAT environments).
    """
    auth: Optional[str] = request.headers.get("Authorization", "")
    if auth and auth.startswith("Bearer oc_"):
        # Use first 16 chars of the token as the bucket key (not the full secret)
        token = auth.split(" ", 1)[1]
        return f"key:{token[:16]}"
    return f"ip:{get_remote_address(request)}"


# Single shared limiter instance — imported by the FastAPI app
limiter = Limiter(key_func=_key_func, default_limits=[RATE_PROCESS])