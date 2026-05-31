# Node 001 Daily Operations Runbook

**Version:** 1.0  
**Effective:** Upon Node 001 Deployment  
**Audience:** On-site operators, stewards, community coordinators  

---

## Morning Checklist (06:00 Daily)

### Energy System Status (5 min)
```bash
curl http://localhost:8000/health/energy
# Expected response:
{
  "waterwheel_generation": 2100,  # watts
  "solar_generation": 18500,       # watts (varies with season/weather)
  "battery_soc": 75,               # state of charge %
  "total_available": 20600,        # watts
  "status": "NOMINAL"
}
```

**Actions if ALERT:**
- [ ] Waterwheel generation <1500W → Check water intake for blockage
- [ ] Solar <10kW → Normal if cloudy; check panel cleanliness if clear skies
- [ ] Battery SOC <20% → Activate load-shedding protocol (see below)
- [ ] Total <15kW → Initiate emergency procedures

### Water System Status (5 min)
```
Check Points:
  [ ] Pressure gauge: 40-60 PSI (main tank)
  [ ] Flow meter: ≥500 GPM (cascade intake)
  [ ] Sediment tank: no visible turbidity
  [ ] Biometric water fountain: operational (residents can refill)
```

**Actions if ALERT:**
- [ ] Pressure <40 PSI → Check for leaks, restart pump if needed
- [ ] Flow <400 GPM → Check intake weir, remove debris
- [ ] Water turbid → Run filter backflush cycle

### Node API Health (5 min)
```bash
curl -X GET http://localhost:8000/health \
  -H "Authorization: Bearer ${ADMIN_KEY}"

# Expected response:
{
  "status": "healthy",
  "node_id": "node-001-bethel",
  "lineage_chain_height": 1042,
  "last_block_timestamp": "2026-05-31T06:00:00Z",
  "seconds_since_last_block": 12,
  "biometric_system": "online",
  "aethel_kernel": "loaded",
  "federation_peers": 0,  # increases as nodes join
  "uptime_seconds": 864000
}
```

**Actions if NOT healthy:**
- [ ] Status != "healthy" → Restart Node service
- [ ] Last block >300 seconds old → Check consensus engine (federation)
- [ ] Biometric system offline → Restart biometric daemon
- [ ] AETHEL kernel missing → Rebuild Rust module

### Census & Safety (2 min)
- [ ] Head count of residents: ___ / ___ expected
- [ ] Any residents missing or reported absent → Follow up immediately
- [ ] No injuries or incidents reported → Document in log
- [ ] Emergency supplies (first aid, water, food) stocked

### Audit Log Review (3 min)
```bash
tail -50 /var/log/openclaw/aethel_vetoes.jsonl
```

**Expect:** 0-3 vetoes per day in normal operation  
**Alert threshold:** >5 vetoes/day = governance stress signal

**Actions if elevated:**
- [ ] Review each veto reason
- [ ] Identify pattern (e.g., "extraction_scan" repeated?)
- [ ] Notify Constitutional Stewards if anomaly
- [ ] Check for coordinated attack attempt

---

## Hourly Energy Management (Every 60 min)

### Energy Balance Calculation
```
Available = Waterwheel + Solar - Usage - Battery_Charging
```

**Track in spreadsheet (or automated dashboard):**
```
Hour | Waterwheel | Solar | Usage | Battery | Balance | Notes
     | (W)        | (W)   | (W)   | (W)     | (W)     |
06:00| 2100       | 0     | 800   | -1300   | 0       | Dawn
07:00| 2100       | 500   | 1200  | -1400   | 0       |
08:00| 2100       | 5000  | 1500  | +5600   | +5200   | Load shed if >6kW
...
```

### Load Management Rules

**If Battery SOC >90% AND Generation >Load:**
- [ ] Activate secondary loads (water heater, EV charger if present)
- [ ] Divert to ORC module (if deployed)
- [ ] Log energy surplus event

**If Battery SOC 20-40%:**
- [ ] Notify residents: "Non-essential loads may experience delays"
- [ ] Reduce computing load (fewer processes)
- [ ] Reduce heating/cooling to essential only
- [ ] Continue biometric/AETHEL systems (always critical)

**If Battery SOC <20%:**
- [ ] EMERGENCY: Activate backup diesel generator
- [ ] Shed all non-critical loads immediately
- [ ] Residents on alert (potential blackout risk)
- [ ] Investigate: Why did we drop to <20%?

### Critical Loads (Always On, No Shedding)
- [ ] Node 001 server + AETHEL kernel
- [ ] Biometric enrollment system
- [ ] Water pumps (gravity feed fails, use backup)
- [ ] Refrigeration (food safety)
- [ ] Lighting (essential corridors, common areas)

### Discretionary Loads (Can Be Shed)
- [ ] Space heating/cooling (if temperature ≥50°F and ≤85°F)
- [ ] EV charger (if present)
- [ ] Laundry facilities (schedule for peak solar hours)
- [ ] Hot water heater (use thermal solar only)

---

## Weekly Operational Review (Monday 09:00)

### System Performance Summary
```markdown
## Week of [DATE]

### Energy Generation
- Waterwheel: ___ kWh (expected: 147 kWh/week)
- Solar: ___ kWh (varies, expected: 400-600 kWh/week)
- ORC: ___ kWh (if deployed)
- **Total: _____ kWh**

### Energy Usage
- Residential: ___ kWh
- Computing: ___ kWh
- Water system: ___ kWh
- **Total: _____ kWh**

### Surplus/Deficit
- Surplus weeks (positive): Store in battery, activate secondary loads
- Deficit weeks (negative): Review usage patterns, identify inefficiencies

### Incidents This Week
- [ ] None
- [ ] List: _______________

### Veto Events This Week
Count by category:
- Gate 0 (biometric): ___
- Gate 1 (consent): ___
- Gate 2 (LQ score): ___
- Gate 3 (extraction): ___
- **Total: ___**

(Expect: 5-15 vetoes/week is normal)

### Maintenance Completed
- [ ] Waterwheel bearing inspection
- [ ] Solar panel cleaning
- [ ] Water filter backflush
- [ ] Node server backup
- [ ] Biometric system calibration check

### Items for Constitutional Stewards
- [ ] Resident concerns: _______________
- [ ] Governance questions: _______________
- [ ] Proposals pending: _______________
```

---

## Failure Scenarios & Recovery

### Scenario 1: Power Outage (Full Node Failure)

**Trigger:** API health check fails for >2 minutes

**Immediate Response (0-5 min):**
```bash
# On UPS (should have battery backup)
sudo systemctl restart openclaw-node

# Check logs
sudo journalctl -u openclaw-node -n 100 --no-pager
```

**If reboot doesn't work (5-15 min):**
```bash
# Restore from last known-good snapshot
cd /var/openclaw
sudo cp -r lineage_chain.db lineage_chain.db.backup
sudo systemctl start openclaw-node --snapshot-restore

# Verify lineage integrity
curl http://localhost:8000/verify/lineage
```

**If still down (15+ min):**
- [ ] Activate EMERGENCY PROTOCOL
- [ ] Manual governance takeover (no AI, human decisions only)
- [ ] Contact federation peers (Node 002, etc) for consensus help
- [ ] Notify residents: "Node is in manual mode until systems restore"

**Recovery Time Target:** <30 minutes from outage to operational

---

### Scenario 2: Water System Failure

**Trigger:** Flow drops <200 GPM for >5 minutes

**Check Immediately:**
1. Intake weir blockage? (visible debris?)
2. Freeze (winter)? (Temperature? Crack in pipes?)
3. Major leak? (Check all joints, radiator pressure)

**Response Steps:**
- [ ] If blockage: Remove debris from intake
- [ ] If freeze: Apply heat wraps to exposed pipes, drain to prevent rupture
- [ ] If leak: Isolate section (close valve), repair
- [ ] Activate backup: switch to well/stored water (if available)

**If system down >2 hours:**
- [ ] Distribute bottled water to residents
- [ ] Limit bathing to essential only
- [ ] Use waterwheel as secondary power (lower output)

---

### Scenario 3: Biometric System Offline

**Trigger:** Enrollment requests fail, biometric_system = "offline"

**Check:**
```bash
sudo systemctl status openclaw-biometric
sudo ps aux | grep biometric
```

**Restart:**
```bash
sudo systemctl restart openclaw-biometric
# Wait 30 seconds for device reinit
curl http://localhost:8000/biometric/status
```

**If device unresponsive (hardware failure):**
- [ ] Switch to MANUAL verification mode
- [ ] Residents verify identity with photo ID + witness
- [ ] Issue temporary tokens (valid 24 hours)
- [ ] Order replacement device (lead time ~2 weeks)

**During manual verification:**
- Gate 0 logic: Visual check (photo + physical match)
- Gate 1-3: Continue as normal
- Approve: "MANUAL_BIOMETRIC_TEMPORARY"
- Document in audit log with witness name

---

### Scenario 4: Lineage Chain Corruption

**Trigger:** AETHELA detects hash mismatch or append failure

**Immediate Action (Do NOT attempt to fix manually):**
```bash
# AETHELA auto-activates READ-ONLY mode
# No new transactions accepted

# Check status
curl http://localhost:8000/lineage/integrity

# Expected output:
{
  "status": "CORRUPTED_READ_ONLY",
  "last_verified_block": 10342,
  "current_block": 10345,
  "unverified_blocks": 3,
  "corruption_detected_at_block": 10343
}
```

**Recovery Steps:**
1. [ ] Notify Constitutional Stewards immediately
2. [ ] Restore from last verified snapshot (block 10342)
3. [ ] Replay verified blocks only (10344-10345 discarded)
4. [ ] Investigate: What caused corruption?
   - Power failure during write?
   - Filesystem error?
   - Malicious tampering?

**Replay command:**
```bash
openclaw-cli lineage restore \
  --snapshot block_10342.verified \
  --replay-only-verified \
  --output lineage_chain.db.recovered
```

**After recovery:**
- [ ] Verify all blocks hash correctly
- [ ] Resume normal operations
- [ ] Log incident to AETHEL audit trail
- [ ] Communities in federation notified

---

### Scenario 5: Governance Deadlock (No Steward Quorum)

**Trigger:** Fewer than 2/3 of stewards available for 48+ hours

**Background:** Constitutional Stewards = 2-3 people (default 3)

**Actions:**
- [ ] At 24 hours: Activate emergency protocol
  - Single steward can make critical operational decisions
  - All decisions logged (will need ratification later)
  - Decisions limited to: safety, health, essential systems

- [ ] At 48 hours: Convene Constitutional Convention
  - Any 5 active residents can participate
  - Temporary governance framework activated
  - Convention votes on emergency measures

- [ ] At 72 hours: Contact federation peers
  - If federation exists, neighboring nodes can provide arbitration
  - External steward observers advise (don't decide)

**Key principle:** Node continues operating. Humans stay safe. Governance adapted, not abandoned.

---

## Resident Onboarding Protocol

### Week 1: Constitutional Education (Self-Paced)

Residents watch/read:
- [ ] MISSION.md (15 min)
- [ ] ESSAY.md (45 min)
- [ ] GOVERNANCE.md (30 min)
- [ ] "How AETHELA Works" video (10 min)

Residents understand:
- [ ] Mission: Protect people who pool their lives
- [ ] 4-gate safety pipeline: Why it exists
- [ ] AETHELA veto: Non-bypassable, by design
- [ ] Covenant: 1% architect, 89% community, 10% system
- [ ] Their rights: Exit within 72 hours, no penalty

### Week 2: Biometric Enrollment Ceremony (Witnessed)

**Process:**
```
1. Resident brings photo ID (proof of identity)
2. Two witnesses present (existing residents or stewards)
3. Iris scan taken (or biometric of choice)
4. Photo ID compared to live face (witnesses sign off)
5. Template stored in secure local database (encrypted)
6. Resident receives: enrollment card with their member_id
7. Steward signs ceremony log
```

**After ceremony:**
- Resident can issue 90-second attestation tokens
- Tokens authenticate all transactions
- Each transaction leaves immutable record
- Resident reviews own audit trail anytime

### Week 3: First Non-Binding Proposal

Residents submit a test proposal:
- Topic: Something low-stakes (e.g., "lunch menu change")
- Runs through full 4-gate pipeline
- Returns APPROVED or BLOCKED
- Resident learns how system responds

**Learning objectives:**
- LQ score calculation (why was I blocked?)
- AETHELA veto reason (what violated the 27 patterns?)
- Lineage chain (see my transaction recorded forever)

### Week 4: Full Participation Enabled

- [ ] Residents can submit binding proposals
- [ ] Residents can vote on governance amendments
- [ ] Residents receive 1/N share of community pool (89% covenant split)
- [ ] Residents gain access to all Help Found You resources
- [ ] Residents invited to community events, decision-making

---

## Monthly Steward Report Template

**Due:** First business day of each month

```markdown
# Node 001 Steward Report — [MONTH YEAR]

## Summary
- Residents: ___ active, ___ departures, ___ new arrivals
- Transactions: ___ total, ___ blocked, ___ controversy
- Energy: ___% surplus vs target
- Incidents: ___ major, ___ minor, ___ resolved

## Constitutional Matters
- Proposals voted: ___
- Amendments proposed: ___
- AETHELA veto events: ___ (detailed breakdown)
- Governance disputes: ___

## Operational Issues
- Systems failures: ___ (list & resolution)
- Maintenance completed: ___________
- Maintenance pending: ___________
- Budget variance: $____

## Community Feedback
- Resident satisfaction: __ / 10 (survey)
- Concerns raised: _______________
- Praise received: _______________
- Suggestions for improvement: _______________

## Covenant Compliance
- 1% architect split: Paid? ___
- 89% community pool: Distributed? ___
- 10% system fund: Used appropriately? ___

## Signed By
- Operational Steward: _________________ Date: _____
- Constitutional Steward: _________________ Date: _____
- Audit Steward: _________________ Date: _____
```

---

## Quick Reference: Emergency Contacts

```
Operator On-Duty: _________________ Phone: _________________
Constitutional Stewards (2-3):
  - _________________ Phone: _________________
  - _________________ Phone: _________________
  - _________________ Phone: _________________

Federation Peer (if exists):
  - Node 002: _________________ URL: _________________

County Emergency:
  - Building Inspector: _________________
  - Water Authority: _________________
  - Sheriff: 911

Medical Emergency: 911
Crisis Lifeline: 988
```

---

**Document Status:** READY FOR DEPLOYMENT  
**Last Updated:** 2026-05-31  
**Node:** 001 — Bethel Acres  

*Keep this runbook at the operator station. Print it. Reference it daily.*
