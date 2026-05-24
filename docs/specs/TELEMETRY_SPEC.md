# OpenClaw Colony — Telemetry Specification v0.7.2

## The Feedback Loop
Field → Telemetry → Spec Delta → Code → CI → Deploy → Field

## Key Metrics
- /health — node status, state, lineage tip
- /federation/status — peers, proposals, lineage count
- gate_0_failures > 10/hour → ALERT (spoof attack)
- node_state = ISOLATED > 5min → ALERT (federation breakdown)
- install_success_rate < 99% → ALERT (access vector violated)
