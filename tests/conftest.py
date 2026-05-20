"""
Global pytest configuration for OpenClaw Colony test suite.

Sets safe environment defaults BEFORE any module is imported so that
individual test files don't bleed env-var state into each other.

Rules:
  - Biometric is OFF by default (test_biometric.py enables it per-test)
  - DB is in-memory
  - Auth is disabled
  - Rate limits are high (avoid 429s in unit tests)
"""

import os
import sys

# ── Ensure backend/ is on sys.path so all colony modules are importable ───────
_backend = os.path.join(os.path.dirname(__file__), "..", "backend")
if _backend not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend))

# ── Safe defaults applied before any test module is collected ─────────────────

os.environ.setdefault("COLONY_DB_PATH",
                      "file:colony_test_global?mode=memory&cache=shared&uri=true")
os.environ.setdefault("COLONY_AUTH_ENABLED", "false")
os.environ.setdefault("COLONY_ADMIN_KEY", "test-admin-secret")

# Biometric OFF by default — test_biometric.py patches per-test as needed
os.environ.setdefault("COLONY_BIOMETRIC_REQUIRED", "false")
os.environ.setdefault("COLONY_LIVENESS_THRESHOLD", "0.95")
os.environ.setdefault("COLONY_ATTESTATION_TTL", "90")

# Rate limits — high values so unit tests never hit 429
os.environ.setdefault("COLONY_RATE_PROCESS", "10000/minute")
os.environ.setdefault("COLONY_RATE_WEBHOOK", "10000/minute")
os.environ.setdefault("COLONY_RATE_ADMIN",   "10000/minute")