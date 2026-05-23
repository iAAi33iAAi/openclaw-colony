# OpenClaw Colony  Formal Governance Specification
**Version 1.0  Constitutional Document  May 23, 2026**
**Node 001  Bethel Acres**

---

## Article 1  Constitutional Purpose

This document is the canonical constitutional substrate of the OpenClaw Colony system.

It is not philosophy. It is not branding. It is institutional law.

**Purpose:** To preserve human sovereignty, ethical coordination, resource transparency, and constitutional continuity within all OpenClaw systems  present and federated.

This specification governs: all authority relationships within the system, all boundaries of automated enforcement, all rights that cannot be removed by any actor, all procedures for constitutional mutation, and all conditions under which emergency powers may be invoked and must expire.

---

## Article 2  Sovereignty Model

Authority within OpenClaw is partitioned across five layers. No layer holds absolute power over all others.

| Layer | Authority Class | Scope |
|---|---|---|
| Humans | Ultimate sovereignty | Cannot be overridden by any system actor |
| Stewards | Operational governance | Elected, term-limited, removable |
| AETHELA | Bounded constitutional enforcement | Veto and halt only  cannot legislate |
| Agents | No sovereign authority | Execute within steward-defined parameters |
| Federation Peers | Autonomous but treaty-bound | Local sovereignty preserved; invariants required |

The fundamental rule: Sovereignty flows upward. No layer may expand its own authority without ratification by a higher layer.

---

## Article 3  Non-Amendable Rights

The following rights are constitutional bedrock. No amendment process, emergency declaration, steward vote, or AETHELA action may suspend, modify, or remove them.

### 3.1 Human Override Rights
Every human participant retains the unconditional right to halt any automated process affecting their resources, review any decision affecting their participation, and require human review before irreversible actions are executed.

### 3.2 Exit Rights
Every human participant retains the unconditional right to exit any colony at any time, receive a complete data export, have their exit processed within 72 hours, and exit without penalty, coercion, or loss of accrued legitimate resources.

### 3.3 Auditability
Every participant retains the right to inspect the full audit log of all actions affecting them, receive a SHA-256 verifiable copy of their transaction lineage, and know the identity of any steward who made a decision affecting them.

### 3.4 Consent
No participant shall be subject to biometric collection without explicit informed consent, automated decision-making affecting their resources without prior disclosure, or modification of consent terms without individual notification and re-consent.

### 3.5 Data Sovereignty
Participant data shall not be sold, licensed, or transferred to third parties without explicit individual consent, used for purposes outside the stated colony mission, or retained after lawful exit beyond what is required for audit continuity.

### 3.6 Anti-Coercion
No system actor, steward, or federated node may use resource withholding as coercion, threaten exit penalties to prevent participation withdrawal, or use audit data as leverage in disputes.

---

## Article 4  AETHELA Boundary Conditions

AETHELA is the constitutional enforcement kernel. Its authority is absolute within its defined boundaries  and those boundaries are themselves non-amendable without supermajority ratification.

### 4.1 What AETHELA CAN Do

| Action | Trigger Condition |
|---|---|
| Veto transaction execution | Invariant violation detected |
| Freeze memory state | Corruption or integrity breach detected |
| Halt agent execution | Unauthorized authority expansion detected |
| Require steward review | Constitutional ambiguity detected |
| Quarantine federated node | Invariant violation from peer detected |
| Restore from verified snapshot | Integrity failure confirmed |
| Activate emergency read-only mode | Multiple simultaneous integrity failures |

### 4.2 What AETHELA CANNOT Do

| Prohibited Action | Reason |
|---|---|
| Amend or reinterpret constitutional invariants | Legislation requires steward ratification |
| Permanently suspend human sovereignty | Non-amendable right |
| Self-expand its own authority boundaries | Requires higher-layer ratification |
| Override a ratified steward amendment | Enforcement is not veto of legitimate governance |
| Prevent lawful participant exit | Non-amendable right |
| Confiscate participant assets beyond halt | Asset authority belongs to stewards |
| Appoint or remove stewards unilaterally | Steward governance is human-layer authority |

### 4.3 AETHELA Veto Semantics

AETHELA's veto is binary and bounded: ALLOW (execution proceeds) or VETO (execution halts, reason logged, steward review triggered). AETHELA does not negotiate, arbitrate, or suggest. All AETHELA actions are immediately logged, human-readable, and steward-reviewable within 24 hours.

---

## Article 5  Steward Governance

### 5.1 Steward Classes

| Class | Role | Count |
|---|---|---|
| Operational Stewards | Day-to-day colony administration | 3-7 |
| Constitutional Stewards | Amendment and invariant oversight | 2-3 |
| Audit Stewards | Independent audit chain verification | 1-2 |

### 5.2 Election and Selection
Stewards are elected by active participants with minimum 30-day participation history. Election requires simple majority. All elections are logged to the audit chain with vote counts.

### 5.3 Term Limits
- Operational Stewards: 12-month terms, maximum 2 consecutive terms
- - Constitutional Stewards: 18-month terms, maximum 1 consecutive term
  - - Audit Stewards: 24-month terms, maximum 1 consecutive term
   
    - ### 5.4 Quorum Requirements
   
    - | Action Type | Quorum Required |
    - |---|---|
    - | Operational decisions | Simple majority of Operational Stewards |
    - | Emergency declaration | 2/3 of all active stewards |
    - | Constitutional amendment | 3/4 of all active stewards + 30-day review |
    - | Steward removal | 2/3 of remaining stewards + audit review |
   
    - ### 5.5 Emergency Powers
   
    - Emergency powers may be invoked by 2/3 steward vote when AETHELA detects systemic integrity failure, a federated node initiates a hostile action, or critical infrastructure failure threatens participant assets.
   
    - Limits: Maximum 72 hours without renewal. Renewal requires 3/4 vote. Maximum 14 consecutive days  after which constitutional convention is automatically triggered.
   
    - Never available under emergency powers: suspension of exit rights, suspension of auditability, modification of non-amendable rights, permanent invariant changes.
   
    - ### 5.6 Steward Removal
    - A steward may be removed by 2/3 vote of remaining stewards following documented cause, audit finding of deliberate log manipulation, confirmed invariant violation, or failure to fulfill audit obligations for 30 consecutive days. Removal is logged permanently. Removed stewards retain exit rights.
   
    - ### 5.7 Steward Audit Obligations
    - Each steward must review all AETHELA veto events within 24 hours, publish a monthly operational summary to the audit chain, disclose material conflicts of interest within 48 hours, and sign all steward decisions with their registered key.
   
    - ---

    ## Article 6  Amendment Process

    ### 6.1 Amendment Classes

    | Class | Scope | Threshold |
    |---|---|---|
    | Operational Amendment | Agent parameters, steward procedures, resource rules | Simple majority stewards |
    | Structural Amendment | Steward classes, quorum rules, emergency procedures | 3/4 stewards + 14-day review |
    | Constitutional Amendment | Sovereignty model, AETHELA boundaries, federation treaty | 3/4 stewards + supermajority participants + 30-day review |
    | Non-Amendable Provisions | Article 3 rights, AETHELA Cannot list | Cannot be amended by any process |

    ### 6.2 Amendment Procedure
    1. Proposal: any participant may submit; requires steward co-signature to advance
    2. 2. Review Period: minimum 14 days structural, 30 days constitutional
       3. 3. Public Comment: logged to audit chain, steward response required
          4. 4. Vote: quorum as defined in Article 6.1
             5. 5. Ratification Delay: 7-day waiting period after vote before implementation
                6. 6. Implementation: logged to audit chain with full vote record
                   7. 7. Rollback Window: 30-day rollback available by 3/4 steward vote
                     
                      8. ### 6.3 Veto Conditions
                      9. The Architect retains constitutional assent authority for amendments affecting the Architect's Covenant terms, AETHELA's core enforcement boundaries, and non-amendable rights. This authority is non-delegable and expires upon formal succession.
                     
                      10. ---
                     
                      11. ## Article 7  Architect Authority and Succession
                     
                      12. ### 7.1 Architect Role
                      13. The Architect holds covenant authority established at system genesis  not operational authority. The Architect holds veto over amendments affecting the Architect's Covenant, cannot direct day-to-day operations, cannot override steward governance decisions, and cannot suspend non-amendable rights.
                     
                      14. ### 7.2 Succession Procedure
                      15. 1. Constitutional Stewards convene within 7 days of Architect incapacity
                          2. 2. Stewards nominate successor candidates from the active contributor registry
                             3. 3. Federation nodes are notified and may submit commentary (non-binding)
                                4. 4. 3/4 steward vote confirms successor
                                   5. 5. Successor accepts constitutional obligations in writing, logged to audit chain
                                      6. 6. AETHELA logs succession event as constitutional milestone
                                        
                                         7. Succession does not reset or modify any constitutional provisions. The covenant transfers intact.
                                        
                                         8. ---
                                        
                                         9. ## Article 8  Federation Treaty Model
                                        
                                         10. ### 8.1 Federation Principles
                                         11. Federation is opt-in and revocable. No node is compelled to federate. Federated nodes retain local sovereignty in all matters not covered by the treaty model.
                                        
                                         12. ### 8.2 Treaty Requirements
                                         13. A node may federate only if it implements the constitutional invariants defined in this document, maintains an append-only audit chain verifiable by peer nodes, preserves participant exit rights without exception, and does not deploy surveillance capabilities targeting federated participants.
                                        
                                         14. ### 8.3 Federation Rights
                                         15. Federated nodes may maintain local governance models, reject specific cross-node proposals without losing federation status, audit peer nodes via the federation audit protocol, and voluntarily defederate at any time.
                                        
                                         16. ### 8.4 Federation Obligations
                                         17. Federated nodes must report AETHELA-detected invariant violations to the federation within 24 hours, not host actors formally expelled for invariant violations, and honor participant data portability requests from peer nodes.
                                        
                                         18. ### 8.5 Isolation and Expulsion
                                         19. A node may be isolated by 2/3 vote of federation stewards pending investigation. Formal expulsion requires 3/4 vote for deliberate invariant violation, harboring expelled actors, or systematic audit chain forgery. No node may be expelled without a 14-day investigation period except during confirmed active attack. No node may unilaterally force defederation of another.
                                        
                                         20. ---
                                        
                                         21. ## Article 9  Auditability Requirements
                                        
                                         22. ### 9.1 Audit Chain Structure
                                         23. The OpenClaw audit chain is: append-only, SHA-256 chained, publicly readable, and steward-signed.
                                        
                                         24. ### 9.2 Required Audit Events
                                        
                                         25. | Event | Required Fields |
                                         26. |---|---|
                                         27. | AETHELA veto | timestamp, trigger, affected transaction, steward notified |
                                         28. | Steward election | candidates, vote counts, outcome, effective date |
                                         29. | Steward removal | cause, vote record, effective date |
                                         30. | Emergency declaration | trigger, declaring stewards, expiration timestamp |
                                         31. | Constitutional amendment | proposal text, vote record, ratification date, rollback window |
                                         32. | Participant exit | timestamp, resources returned, data export confirmation |
                                         33. | Federation event | node identifier, event type, steward vote record |
                                         34. | Succession | outgoing Architect, incoming Architect, vote record |
                                         35. | Memory restoration | snapshot hash, trigger event, restoring authority |
                                        
                                         36. ### 9.3 Audit Integrity Failure
                                         37. If the audit chain integrity check fails: AETHELA immediately activates read-only mode, stewards are notified within 60 seconds, last verified snapshot hash is published, no transactions are processed until integrity is restored, and restoration requires steward authorization and AETHELA verification.
                                        
                                         38. ---
                                        
                                         39. ## Article 10  Failure, Dissolution, and Recovery
                                        
                                         40. ### 10.1 Constitutional Freeze
                                         41. AETHELA may declare a constitutional freeze when audit chain integrity cannot be restored, steward quorum cannot be achieved for more than 30 days, or a critical invariant cannot be enforced. During a freeze: no new transactions are processed, participant assets are locked in read-only state, exit rights remain active, and stewards have 30 days to restore quorum.
                                        
                                         42. ### 10.2 Node Dissolution
                                         43. A node may be dissolved by unanimous steward vote, 30-day constitutional freeze without restoration, or 2/3 participant vote. Upon dissolution: all participant assets are returned within 72 hours, full data export is provided, audit chain is sealed and archived publicly, and federation peers are notified.
                                        
                                         44. ### 10.3 Governance Reboot
                                         45. After 30-day steward vacancy, any 5 active participants may convene a constitutional convention operating under this document's amendment procedures. A reboot does not modify non-amendable rights.
                                        
                                         46. ### 10.4 Recovery Authority
                                         47. 1. Active stewards (if quorum achievable)
                                             2. 2. Constitutional convention (if steward quorum is not achievable)
                                                3. 3. Federation arbitration (if convention cannot be convened)
                                                  
                                                   4. No recovery procedure may modify non-amendable rights or suspend exit rights.vent type, steward vote record |
                                                   5. | Succession | outgoing Architect, incoming Architect, vote record |
                                                   6. | Memory restoration | snapshot hash, trigger event, restoring authority |
                                                  
                                                   7. ### 9.3 Audit Integrity Failure
                                                   8. If the audit chain integrity check fails: AETHELA immediately activates read-only mode, stewards are notified within 60 seconds, last verified snapshot hash is published, no transactions are processed until integrity is restored, and restoration requires steward authorization and AETHELA verification.
                                                  
                                                   9. ---
                                                  
                                                   10. ## Article 10 - Failure, Dissolution, and Recovery
                                                  
                                                   11. ### 10.1 Constitutional Freeze
                                                   12. AETHELA may declare a constitutional freeze when audit chain integrity cannot be restored, steward quorum cannot be achieved for more than 30 days, or a critical invariant cannot be enforced. During a freeze: no new transactions are processed, participant assets are locked in read-only state, exit rights remain active, and stewards have 30 days to restore quorum.
                                                  
                                                   13. ### 10.2 Node Dissolution
                                                   14. A node may be dissolved by unanimous steward vote, 30-day constitutional freeze without restoration, or 2/3 participant vote. Upon dissolution: all participant assets are returned within 72 hours, full data export is provided, audit chain is sealed and archived publicly, and federation peers are notified.
                                                  
                                                   15. ### 10.3 Governance Reboot
                                                   16. After 30-day steward vacancy, any 5 active participants may convene a constitutional convention operating under this document's amendment procedures. A reboot does not modify non-amendable rights.
                                                  
                                                   17. ### 10.4 Recovery Authority
                                                   18. 1. Active stewards (if quorum achievable)
                                                       2. 2. Constitutional convention (if steward quorum is not achievable)
                                                          3. 3. Federation arbitration (if convention cannot be convened)
                                                            
                                                             4. No recovery procedure may modify non-amendable rights or suspend exit rights.
                                                            
                                                             5. ---
                                                            
                                                             6. ## Article 11 - Implementation Notes
                                                            
                                                             7. This governance specification becomes binding upon AETHELA enforcement boundary configuration, deployment of the invariant test suite, and steward registry initialization.
                                                            
                                                             8. **Constitutional version:** 1.0
                                                             9. **Effective date:** May 23, 2026
                                                             10. **Node:** 001 - Bethel Acres
                                                             11. **Architect's mark:** iAAi33iAAi
                                                            
                                                             12. *This document is given under GNU AGPL v3 + Architect's Covenant. The governance model itself is open. The covenant terms are preserved in all derivatives.*
                                                  
                                                   19. ---
                                                  
                                                   20. ## Article 11  Implementation Notes
                                                  
                                                   21. This governance specification becomes binding upon AETHELA enforcement boundary configuration, deployment of the invariant test suite, and steward registry initialization.
                                                  
                                                   22. **Constitutional version:** 1.0
                                                   23. **Effective date:** May 23, 2026
                                                   24. **Node:** 001  Bethel Acres
                                                   25. **Architect's mark:** iAAi33iAAi
                                                  
                                                   26. *This document is given under GNU AGPL v3 + Architect's Covenant. The governance model itself is open. The covenant terms are preserved in all derivatives.*
