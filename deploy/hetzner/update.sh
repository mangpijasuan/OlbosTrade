#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# OlbosTrade — Pull latest code and redeploy (zero-downtime rolling restart)
#
# Run from /opt/olbostrade on the server:
#   bash deploy/hetzner/update.sh
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

set -a
source backend/.env.prod
set +a

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  OlbosTrade — Updating"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "[1/4] Pulling latest code..."
git pull origin main
echo "      ✅ Code updated"

echo "[2/4] Rebuilding containers..."
docker compose -f docker-compose.hetzner.yml build --no-cache backend frontend
echo "      ✅ Images rebuilt"

echo "[3/4] Restarting containers..."
docker compose -f docker-compose.hetzner.yml up -d
echo "      ✅ Containers restarted"

echo "[4/4] Running migrations..."
# Wait briefly for backend to come up
sleep 5
docker exec olbosquant-backend python3 -m alembic upgrade head
echo "      ✅ Migrations applied"

echo ""
echo "  ✅ Update complete"
echo "     docker logs olbosquant-backend -f   ← watch logs"
