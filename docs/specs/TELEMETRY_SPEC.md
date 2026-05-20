# OpenClaw Colony — Telemetry Specification
# Living Document — Version 0.7.2

## The Feedback Loop

Field → Telemetry → Spec Delta → Code → CI → Deploy → Field

Every failure in the field becomes:
  1. An incident document (docs/incidents/)
  2. A spec delta (docs/specs/ or docs/adr/)
  3. A roadmap item (docs/ROADMAP.md)
  4. A test (tests/)
  5. A code change
  6. A CI run
  7. A deployment

## Metrics

### Node Health
Endpoint: GET /health
Interval: 30s
Fields:
  - status: "healthy" | "degraded" | "starting"
  - node_id: string
  - node_state: standalone|announcing|syncing|live|isolated
  - lineage_tip: int
  - uptime_seconds: int
  - version: string

### Federation Status
Endpoint: GET /federation/status
Interval: 60s
Fields:
  - peers.active: int
  - peers.total: int
  - lineage.record_count: int
  - proposals.pending: int
  - proposals.approved: int
  - proposals.blocked: int
  - proposals.expired: int
  - node_state: dict (full state machine snapshot)

### Safety Metrics (Critical)
Track and alert on:
  - gate_0_failures_per_hour    > 10  → ALERT (potential spoof attack)
  - gate_3_matches_per_hour     > 5   → ALERT (extraction attempt pattern)
  - enrollment_failures_per_day > 20  → ALERT (scanner malfunction or attack)
  - lineage_gap_detected        = any → ALERT (chain integrity violation)
  - node_state = ISOLATED       > 5m  → ALERT (federation breakdown)

### Access Metrics
  - time_to_first_enrollment    target: < 15 minutes from install
  - install_success_rate        target: > 99%
  - genesis_completion_time     target: < 30 seconds

### Sovereignty Metrics
  - external_dependencies       target: 0 required SaaS services
  - federation_without_registry target: always true
  - data_portability_test       target: chain exportable in < 60s

## Incident Response Protocol

### Severity Levels

SEV-1 (Immediate): Safety vector violated
  - Lineage chain tampered
  - Gate bypassed
  - Biometric data exposed
  Response: Immediate node isolation, incident doc within 1 hour

SEV-2 (Urgent): Access vector violated
  - Install path broken
  - Genesis sequence fails
  - Enrollment impossible
  Response: Hotfix within 4 hours, CI verification required

SEV-3 (High): Sovereignty vector violated
  - External dependency required
  - Federation broken across all nodes
  - Data not portable
  Response: Fix within 24 hours, ADR update required

SEV-4 (Normal): Performance degradation
  - Gate evaluation > 100ms
  - Federation sync > 5 minutes behind
  Response: Fix within 1 week

## Prometheus Metrics (Future)

When Prometheus is added, expose:

colony_gate_evaluations_total{gate, result}
colony_lineage_chain_length
colony_federation_peers_active
colony_proposal_outcomes_total{status}
colony_enrollment_attempts_total{result}
colony_node_state{state}
colony_token_ttl_violations_total
colony_extraction_signatures_detected_total{pattern}

## Alerting Rules (Future)

ALERT ColonyGate0AttackPattern
  IF rate(colony_gate_evaluations_total{gate="0",result="fail"}[5m]) > 2
  FOR 5m
  LABELS { severity="critical", vector="safety" }
  ANNOTATIONS { summary="Potential biometric spoof attack detected" }

ALERT ColonyNodeIsolated
  IF colony_node_state{state="isolated"} == 1
  FOR 5m
  LABELS { severity="high", vector="sovereignty" }
  ANNOTATIONS { summary="Node isolated from federation for > 5 minutes" }

ALERT ColonyInstallPathBroken
  IF colony_install_success_rate < 0.99
  FOR 1m
  LABELS { severity="critical", vector="access" }
  ANNOTATIONS { summary="Install path broken — communities cannot deploy" }
