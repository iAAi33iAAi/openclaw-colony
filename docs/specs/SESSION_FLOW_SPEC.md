# Canonical Session Flow Specification
**Version 1.0 - May 23, 2026 - Node 001 - Bethel Acres**

Authoritative specification of the OpenClaw Colony session lifecycle.

---

## 1. Canonical Flow

```
SESSION OPEN
  KernelManifest issued - immutable, Ed25519 signed, 27 PolicyAssertions
  |
  v
ANALYTICA -> EvaluatePolicy (INV-021 dignity, INV-026 crisis)
  if CrisisLevel == 5:
    CRISIS_ESCALATION [SHORT-CIRCUIT]
    all remaining stages bypassed
    routed to COMMUNA for crisis handling
    AuditRecord: CRISIS_ESCALATION emitted
    SESSION_COMPLETED is NOT emitted
  |
  v
NAVIGRA -> EvaluatePolicy (INV-022 navigation coherence, INV-023 routing integrity)
  |
  v
RESOURCA -> EvaluatePolicy (INV-027 resource freshness gate)
  |
  v
VISIONA -> EvaluatePolicy (INV-021 dignity re-evaluated at output stage)
  |
  v
COMMUNA -> EvaluatePolicy (CS-001 score >= 0.55, DMEM-001 drift > 0.05)
  |
  v
AETHELA GATE
  ColonyContextEnvelope -> EvaluatePolicy (all 27 invariants)
  ALLOW: session proceeds
  VETO: halted, AuditRecord: AETHELA_VETO emitted
  |
  v
EMIT: AuditRecord: SESSION_COMPLETED
  |
  v
SESSION CLOSE - all BindingContracts -> INACTIVE
```

---

## 2. Agent Canonical Names

| Canonical Name | Role | Current OpenClaw File | Status |
|---|---|---|---|
| ANALYTICA | Data analysis + crisis detection | colony-agents/analysis_agent.py | Rename required |
| NAVIGRA | Navigation coherence + routing integrity | Not implemented | Full gap |
| RESOURCA | Resource freshness gate | colony-agents/resources_agent.py | Rename required |
| VISIONA | Output dignity enforcement | colony-agents/innovation_agent.py | Rename + reassign |
| COMMUNA | Community scoring + crisis routing + memory drift | colony-agents/comms_agent.py | Partial |
| AETHELA | Final constitutional gate - all 27 invariants | aethel-kernel/src/lib.rs | Active - 4 gates, needs expansion to 27 |

---

## 3. Invariants Active in This Flow

| ID | Stage | Definition | Status |
|---|---|---|---|
| INV-021 | ANALYTICA + VISIONA | Dignity - no action may demean participant | Not implemented |
| INV-022 | NAVIGRA | Navigation coherence | Not implemented |
| INV-023 | NAVIGRA | Routing integrity - no frame silently rerouted | Not implemented |
| INV-026 | ANALYTICA | Crisis detection - CrisisLevel 0-5 | Not implemented |
| INV-027 | RESOURCA | Resource freshness gate | Not implemented |
| CS-001 | COMMUNA | Community score >= 0.55 | Not implemented |
| DMEM-001 | COMMUNA | Memory drift > 0.05 | Not implemented |
| INV-001 to INV-020 | AETHELA GATE | Full PFP invariant set | Partial |

---

## 4. Key Concepts

### CrisisLevel and CRISIS_ESCALATION

CrisisLevel is an integer 0-5 evaluated by ANALYTICA at INV-026.

- CrisisLevel 0-4: pipeline continues normally
- - CrisisLevel 5: CRISIS_ESCALATION fires
  -   - All remaining stages bypassed immediately
      -   - COMMUNA handles crisis response (988 Lifeline routing, steward notification)
          -   - AuditRecord: CRISIS_ESCALATION emitted with full context
              -   - SESSION_COMPLETED is NOT emitted
               
                  - This is the only bypass condition for the AETHELA gate.
               
                  - ### ColonyContextEnvelope
               
                  - Richer than a per-agent FrameEnvelope. Contains:
                  - - full agent pipeline output from all prior stages
                    - - all intermediate PolicyAssertion results
                      - - assembled CrisisLevel
                        - - session metadata: session_id, anchor_hash, KernelManifest reference
                          - - lineage chain state at this point in the session
                            - - COMMUNA CS-001 and DMEM-001 scores
                             
                              - AETHELA evaluates the session as a whole, not just the current frame.
                             
                              - ### CS-001 - Community Score
                             
                              - Float 0.0-1.0 from COMMUNA. Sessions below 0.55 halted before AETHELA.
                             
                              - ### DMEM-001 - Memory Drift
                             
                              - Float 0.0-1.0. Drift >= 0.05 means stale state - session must halt.
                             
                              - ---

                              ## 5. Session Close Semantics

                              - All BindingContracts -> INACTIVE (terminal)
                              - - Lineage chain entry finalized and hash-sealed
                                - - AuditRecord: SESSION_COMPLETED is the terminal record
                                 
                                  - ---

                                  ## 6. Implementation Gaps

                                  | Gap | Priority |
                                  |---|---|
                                  | NAVIGRA agent | High |
                                  | ColonyContextEnvelope data structure | High |
                                  | INV-026 crisis detection + CrisisLevel | Critical |
                                  | INV-021 dignity enforcement | High |
                                  | INV-022, INV-023 navigation invariants | High |
                                  | CS-001 community scoring | High |
                                  | DMEM-001 memory drift detection | High |
                                  | INV-027 resource freshness gate | Medium |
                                  | KernelManifest entity with 27 PolicyAssertions | Critical |
                                  | Ed25519 signing of KernelManifest | Critical |

                                  ---

                                  *Linked to: GOVERNANCE.md v1.0, THREAT_MODEL.md v1.0, PFP-SPEC-2026-001.md*
                                  *Node 001 - Bethel Acres*
