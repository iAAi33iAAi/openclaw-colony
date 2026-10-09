"""Regression guards for the execution-admission safety state.

These tests intentionally do not claim that the full boundary is implemented.
They prevent an ordinary refactor from silently removing the explicit
"incomplete / disabled" posture while the effect-path inventory remains open.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "audit" / "EXECUTION_PATH_INVENTORY.yaml"
STRIPE_BRIDGE_PATH = ROOT / "backend" / "stripe_bridge.py"


def test_execution_inventory_stays_incomplete_and_model_execution_disabled():
    inventory = INVENTORY_PATH.read_text(encoding="utf-8")

    assert re.search(
        r'(?m)^status: "INCOMPLETE_INITIAL_SNAPSHOT"$',
        inventory,
    ), "The route-to-effect inventory must remain explicitly incomplete."
    assert re.search(
        r'(?m)^  complete: false$',
        inventory,
    ), "Unknown effect paths must not be treated as covered."
    assert re.search(
        r'(?m)^  model_assisted_consequential_execution: '
        r'"DISABLED_PENDING_IMPLEMENTATION_AND_REVIEW"$',
        inventory,
    ), "Consequential model-assisted execution must remain disabled."
    assert re.search(
        r"(?m)^release_gate: >-$",
        inventory,
    ), "The inventory must retain its explicit release gate."
    assert "Do not claim system-wide execution admission is implemented" in inventory


def test_live_stripe_admission_flag_defaults_to_disabled_in_source():
    source = STRIPE_BRIDGE_PATH.read_text(encoding="utf-8")
    matches = re.findall(
        r"(?m)^LIVE_EXECUTION_ADMISSION_IMPLEMENTED\s*=\s*(True|False)\s*$",
        source,
    )

    assert matches == ["False"], (
        "Live Stripe admission must remain unimplemented and non-enabled until "
        "the signed receipt verifier and boundary tests are reviewed."
    )
