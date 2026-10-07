#!/usr/bin/env python3
"""AETHEL deployment admission gate.

This gate is intentionally conservative: it checks that the repository's
constitutional contract is present and that the declared MANNA allocation,
SPEC-004 conformance fixtures, and critical safety files are internally
consistent before deployment.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAIL = []


def require(path: str) -> str:
    p = ROOT / path
    if not p.is_file():
        FAIL.append(f"missing:{path}")
        return ""
    return p.read_text(encoding="utf-8", errors="strict")


def main() -> int:
    license_text = require("LICENSE")
    stripe = require("backend/stripe_bridge.py")
    covenant_tests = require("tests/test_covenant.py")
    ci = require(".github/workflows/ci.yml")
    spec = require("CAIOS_INTEGRATION.md")
    require("backend/aethel-kernel/src/lib.rs")
    require("backend/aethel_interface.py")

    # The repository license is the authoritative covenant for this deployment.
    if "1% to the Architect" not in license_text:
        FAIL.append("license:missing-1-percent-covenant")
    if "84% to the Community" not in license_text:
        FAIL.append("license:missing-84-percent-community")
    if "15% to the Crew" not in license_text:
        FAIL.append("license:missing-15-percent-crew")

    # Runtime implementation must use the same integer-cent allocation.
    if "architect_cents = round(total_cents * 0.01)" not in stripe:
        FAIL.append("runtime:architect-split-not-1-percent")
    if "crew_cents      = round(total_cents * 0.15)" not in stripe:
        FAIL.append("runtime:crew-split-not-15-percent")
    if "community_cents = total_cents - crew_cents - architect_cents" not in stripe:
        FAIL.append("runtime:remainder-not-community")

    # Tests and CI must enforce the same values.
    for needle, label in [
        ("architect_cents == 100", "tests:architect-not-1-percent"),
        ("community_cents == 8400", "tests:community-not-84-percent"),
        ("architect_cents == 100", "ci:architect-not-1-percent"),
        ("community_cents == 8400", "ci:community-not-84-percent"),
    ]:
        if needle not in (covenant_tests if label.startswith("tests") else ci):
            FAIL.append(label)

    if "CAIOS" not in spec or "AETHEL" not in spec:
        FAIL.append("integration:boundary-document-incomplete")

    result = {"status": "PASS" if not FAIL else "BLOCK", "failures": FAIL}
    print(json.dumps(result, indent=2))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
