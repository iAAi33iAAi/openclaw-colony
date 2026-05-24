# Node Operations Guide
## Full-Stack Technical Audit — Deliverable 6 of 8

---

## Prerequisites

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| OS | Linux (Debian/Ubuntu) | Ubuntu 22.04 LTS |
| RAM | 512MB | 2GB |
| Disk | 2GB | 20GB |
| CPU | 1 core | 2 cores |
| Docker | 24.x | Latest |
| Docker Compose | 2.x | Latest |
| Public IP | Optional | Required for federation |

---

## Quick Start (5 minutes)

```bash
# 1. Install
curl -sSL https://raw.githubusercontent.com/iAAi33iAAi/openclaw-colony/main/install.sh | bash

# 2. Verify
curl http://localhost:8000/health
# Expected: {"status": "healthy", "node_id": "node-001-bethel"}

# 3. Check genesis
curl http://localhost:8000/federation/status \
  -H "Authorization: Bearer YOUR_ADMIN_KEY"
# Expected: lineage.record_count >= 1
```

---

## Manual Setup

```bash
# Clone
git clone https://github.com/iAAi33iAAi/openclaw-colony.git
cd openclaw-colony

# Configure
cp .env.example .env
nano .env  # Edit required values

# Deploy
docker compose up -d

# Verify
docker compose logs backend --tail=50
```

---

## Required Environment Variables

```bash
# CRITICAL — must be set before first run
COLONY_NODE_ID=node-001-bethel          # Unique node name
COLONY_NODE_URL=https://your-node.com   # Public URL
COLONY_BAS_SECRET=<64-char-hex>         # Biometric token HMAC key
                                        # Generate: openssl rand -hex 32
                                        # WARNING: if unset, ephemeral key used
                                        # All tokens invalidated on restart

COLONY_ADMIN_KEY=<32-char-hex>          # Federation + admin auth
                                        # Generate: openssl rand -hex 16

# Optional — defaults shown
COLONY_BIOMETRIC_REQUIRED=true          # Set false for dev only
COLONY_DEV_MODE=false                   # Set true for dev only
COLONY_DB_PATH=/data/colony.db          # SQLite path
COLONY_PEERS=                           # Comma-separated peer URLs
FEDERATION_SYNC_INTERVAL=60             # Gossip interval (seconds)
FEDERATION_QUORUM=0.51                  # Quorum fraction
PROPOSAL_TTL_HOURS=72                   # Proposal expiry
NODE_ISOLATION_TIMEOUT=180              # Isolation detection (seconds)

# Stripe (optional — mock mode if unset)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_COMMUNITY_ACCOUNT=acct_...
STRIPE_CREW_ACCOUNT=acct_...
STRIPE_ARCHITECT_ACCOUNT=acct_...
STRIPE_WEBHOOK_SECRET=whsec_...
COLONY_MANNA_CENTS=100
```

---

## Verification Checklist

After deployment, verify each item:

```
□ GET /health → {"status": "healthy"}
□ GET /federation/status → node_state: "standalone" or "live"
□ lineage.record_count >= 1 (genesis block exists)
□ URL starts with https:// (TLS active)
□ Node reachable from external IP
□ COLONY_BAS_SECRET is set and stable
□ COLONY_ADMIN_KEY is set
□ Docker volumes mounted (data persists across restarts)
```

---

## Federation Setup (Two Nodes)

```bash
# Node 001 .env
COLONY_NODE_ID=node-001-bethel
COLONY_NODE_URL=https://node001.example.com
COLONY_PEERS=https://node002.example.com
COLONY_ADMIN_KEY=shared-secret-both-nodes

# Node 002 .env
COLONY_NODE_ID=node-002-austin
COLONY_NODE_URL=https://node002.example.com
COLONY_PEERS=https://node001.example.com
COLONY_ADMIN_KEY=shared-secret-both-nodes

# Verify federation
curl https://node001.example.com/federation/nodes \
  -H "Authorization: Bearer shared-secret-both-nodes"
# Expected: peers array with node-002-austin listed
```

---

## Health Monitoring

```bash
# Node health
curl http://localhost:8000/health

# Federation status
curl http://localhost:8000/federation/status \
  -H "Authorization: Bearer $COLONY_ADMIN_KEY"

# Lineage chain length
curl http://localhost:8000/federation/status \
  -H "Authorization: Bearer $COLONY_ADMIN_KEY" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['lineage']['record_count'])"

# Docker health
docker compose ps
docker compose logs backend --tail=20
```

---

## Backup and Recovery

```bash
# Backup lineage chain (SQLite)
docker compose exec backend sqlite3 /data/colony.db ".backup /data/colony-backup-$(date +%Y%m%d).db"

# Copy backup off-node
docker cp colony-backend:/data/colony-backup-*.db ./backups/

# Restore
docker compose down
docker cp ./backups/colony-backup-YYYYMMDD.db colony-backend:/data/colony.db
docker compose up -d
```

---

## Upgrading

```bash
# Pull latest
git pull origin main

# Rebuild and restart
docker compose build --no-cache
docker compose up -d

# Verify genesis is idempotent (safe to run again)
docker compose exec backend python dev_commit_init.py
# Expected: {"status": "Genesis_Already_Exists", ...}
```

---

## Secrets Rotation

```bash
# Rotate COLONY_ADMIN_KEY
# 1. Generate new key
NEW_KEY=$(openssl rand -hex 16)

# 2. Update .env on ALL nodes simultaneously
# 3. Restart all nodes
docker compose restart

# WARNING: Rotating COLONY_BAS_SECRET invalidates all biometric tokens
# All enrolled members must re-issue tokens after rotation
# Schedule during maintenance window
```

---

## Missing Operations Docs (Gaps)

| Gap | Priority |
|-----|----------|
| No disaster recovery runbook | HIGH |
| No scaling guide (multiple workers) | MEDIUM |
| No log aggregation setup | MEDIUM |
| No alerting configuration | MEDIUM |
| No database migration guide | MEDIUM |
| No member enrollment ceremony guide | HIGH |
| No biometric hardware setup guide | HIGH |
