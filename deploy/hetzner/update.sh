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

echo "[1/5] Pulling latest code..."
git pull origin main
echo "      ✅ Code updated"

echo "[2/5] Rebuilding containers..."
docker compose -f docker-compose.hetzner.yml build --no-cache backend frontend
echo "      ✅ Images rebuilt"

echo "[3/5] Restarting containers..."
docker compose -f docker-compose.hetzner.yml up -d
echo "      ✅ Containers restarted"

echo "[4/5] Running migrations..."
# Wait briefly for backend to come up
sleep 5
docker exec olbostrade-backend python3 -m alembic upgrade head
echo "      ✅ Migrations applied"

echo "[5/5] Reclaiming build cache..."
# The build above passes --no-cache, so BuildKit writes every layer it produces
# and then never reads any of it. Nothing collected that. By 2026-09-17 it had
# reached 40.83GB across 185 entries — 51GB of /var/lib/containerd on a 75GB
# disk, at 82% full, purely from deploys.
#
# `builder prune -af` is safe precisely BECAUSE of --no-cache: a cache the next
# build is explicitly told to ignore has no value to preserve.
#
# `image prune -f` is dangling-only, deliberately. `-a` would evict any image
# without a running container, and this host runs other compose projects
# (ibkr-gateway, olbos-caddy) whose images would be fair game if they happened
# to be stopped. Rebuilding a tag orphans the image it replaces, so the
# dangling-only sweep already collects exactly this deploy's garbage.
#
# Non-fatal: the deploy succeeded at step 4. `set -e` is on, and failing the
# whole run over cleanup would report a working deployment as broken.
docker builder prune -af  || echo "      ⚠ build cache prune failed — check 'docker system df'"
docker image   prune -f   || echo "      ⚠ dangling image prune failed"
echo "      ✅ Reclaimed"
docker system df

echo ""
echo "  ✅ Update complete"
echo "     docker logs olbostrade-backend -f   ← watch logs"
