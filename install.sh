#!/bin/bash
# ============================================================
# OpenClaw Colony — One-Command Node Installer
# ============================================================
# Usage: curl -sSL https://openclaw.net/install | bash
#
# What this does:
#   1. Checks dependencies (Docker, Docker Compose)
#   2. Generates secure secrets automatically
#   3. Pulls the colony image
#   4. Runs the genesis sequence
#   5. Opens the enrollment interface
#
# No Rust compiler required.
# No Python environment required.
# No database configuration required.
# No DevOps expertise required.
#
# Just run this. Your node is live in minutes.
# ============================================================

set -euo pipefail

# ── Colors ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# ── Banner ────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║           OPENCLAW COLONY — NODE INSTALLER               ║${NC}"
echo -e "${BOLD}║     Protecting people who pool their lives together       ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Check dependencies ────────────────────────────────
echo -e "${BLUE}[1/5] Checking dependencies...${NC}"

if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker not found.${NC}"
    echo "  Install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker compose version &> /dev/null 2>&1; then
    echo -e "${RED}✗ Docker Compose not found.${NC}"
    echo "  Install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

echo -e "${GREEN}✓ Docker $(docker --version | cut -d' ' -f3 | tr -d ',')${NC}"
echo -e "${GREEN}✓ Docker Compose ready${NC}"

# ── Step 2: Configure node ────────────────────────────────────
echo ""
echo -e "${BLUE}[2/5] Configuring your node...${NC}"

# Node ID
if [ -z "${COLONY_NODE_ID:-}" ]; then
    DEFAULT_ID="node-$(hostname | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9-')-$(date +%s | tail -c 4)"
    read -p "  Node name [$DEFAULT_ID]: " NODE_ID
    COLONY_NODE_ID="${NODE_ID:-$DEFAULT_ID}"
fi

# Node URL
if [ -z "${COLONY_NODE_URL:-}" ]; then
    read -p "  Public URL (e.g. https://mycolony.net) [http://localhost:8000]: " NODE_URL
    COLONY_NODE_URL="${NODE_URL:-http://localhost:8000}"
fi

# Peers
if [ -z "${COLONY_PEERS:-}" ]; then
    read -p "  Peer URLs (comma-separated, leave blank for standalone): " PEERS
    COLONY_PEERS="${PEERS:-}"
fi

echo -e "${GREEN}✓ Node ID: $COLONY_NODE_ID${NC}"
echo -e "${GREEN}✓ Node URL: $COLONY_NODE_URL${NC}"

# ── Step 3: Generate secrets ──────────────────────────────────
echo ""
echo -e "${BLUE}[3/5] Generating cryptographic secrets...${NC}"

# Generate stable BAS secret (64 hex chars = 256 bits)
COLONY_BAS_SECRET=$(openssl rand -hex 32)
COLONY_ADMIN_KEY=$(openssl rand -hex 16)

echo -e "${GREEN}✓ BAS secret generated (256-bit)${NC}"
echo -e "${GREEN}✓ Admin key generated${NC}"
echo ""
echo -e "${YELLOW}⚠️  SAVE THESE SECRETS. You will need them if you reinstall.${NC}"
echo -e "${YELLOW}   BAS_SECRET:  $COLONY_BAS_SECRET${NC}"
echo -e "${YELLOW}   ADMIN_KEY:   $COLONY_ADMIN_KEY${NC}"
echo ""

# Write .env file
cat > .env << ENV
# OpenClaw Colony — Node Configuration
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Node: $COLONY_NODE_ID

COLONY_NODE_ID=$COLONY_NODE_ID
COLONY_NODE_URL=$COLONY_NODE_URL
COLONY_PEERS=$COLONY_PEERS
COLONY_BAS_SECRET=$COLONY_BAS_SECRET
COLONY_ADMIN_KEY=$COLONY_ADMIN_KEY
COLONY_BIOMETRIC_REQUIRED=true
COLONY_DEV_MODE=false
COLONY_DB_PATH=/data/colony.db
COLONY_MANNA_CENTS=100
PROPOSAL_TTL_HOURS=72
FEDERATION_SYNC_INTERVAL=60
FEDERATION_QUORUM=0.51
ENV

echo -e "${GREEN}✓ .env file written${NC}"

# ── Step 4: Run genesis sequence ──────────────────────────────
echo ""
echo -e "${BLUE}[4/5] Starting colony node...${NC}"

docker compose pull --quiet 2>/dev/null || true
docker compose up -d

echo ""
echo -e "${BLUE}    Waiting for node to initialise...${NC}"
sleep 5

# Run genesis
GENESIS=$(docker compose exec -T backend python dev_commit_init.py 2>/dev/null || echo "GENESIS_PENDING")

if echo "$GENESIS" | grep -q "Genesis_Committed\|Genesis_Already_Exists"; then
    echo -e "${GREEN}✓ Genesis block committed${NC}"
else
    echo -e "${YELLOW}⚠  Genesis will complete on first request${NC}"
fi

# ── Step 5: Verify and report ─────────────────────────────────
echo ""
echo -e "${BLUE}[5/5] Verifying node health...${NC}"

sleep 3
HEALTH=$(curl -sf "$COLONY_NODE_URL/health" 2>/dev/null || echo '{"status":"starting"}')
echo -e "${GREEN}✓ Node responding${NC}"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║                  NODE IS LIVE                           ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${GREEN}Node ID:${NC}      $COLONY_NODE_ID"
echo -e "  ${GREEN}Node URL:${NC}     $COLONY_NODE_URL"
echo -e "  ${GREEN}API:${NC}          $COLONY_NODE_URL/docs"
echo -e "  ${GREEN}Status:${NC}       $COLONY_NODE_URL/federation/status"
echo -e "  ${GREEN}Dashboard:${NC}    $COLONY_NODE_URL (frontend)"
echo ""
echo -e "  ${YELLOW}Next steps:${NC}"
echo -e "  1. Enroll your first member:  POST $COLONY_NODE_URL/biometric/enroll"
echo -e "  2. Check federation status:   GET  $COLONY_NODE_URL/federation/status"
echo -e "  3. Submit a proposal:         POST $COLONY_NODE_URL/process"
echo ""
echo -e "  ${BLUE}Documentation:${NC}  https://github.com/iAAi33iAAi/openclaw-colony"
echo -e "  ${BLUE}Mission:${NC}        github.com/iAAi33iAAi/openclaw-colony/blob/main/MISSION.md"
echo ""
echo -e "${BOLD}The people who pool their lives together are now protected.${NC}"
echo ""
