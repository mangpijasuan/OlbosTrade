#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# OlbosTrade — First-time start on Hetzner
#
# Run this ONCE after cloning the repo and filling in backend/.env.prod
# From /opt/olbostrade on the server:
#   bash deploy/hetzner/up.sh
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# ── Checks ────────────────────────────────────────────────────────────────────
if [[ ! -f backend/.env.prod ]]; then
  echo "❌  Missing backend/.env.prod"
  echo "    Copy and fill in the template first:"
  echo "    cp deploy/hetzner/.env.example backend/.env.prod && nano backend/.env.prod"
  exit 1
fi

# Load env so docker compose can substitute variables
set -a
source backend/.env.prod
set +a

# Confirm the docker_default network exists (created by OlbosTerminal's Caddy stack)
CADDY_NETWORK=$(docker network ls --format '{{.Name}}' | grep -E '^docker_default$' | head -1)
if [[ -z "$CADDY_NETWORK" ]]; then
  echo "❌  Docker network not found."
  echo "    Make sure the OlbosTerminal app is running first:"
  echo "    cd /root/OlbosTerminal && bash deploy/hetzner/up.sh"
  exit 1
fi
echo "      Using network: $CADDY_NETWORK"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  OlbosTrade — Starting on Hetzner"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Build and start containers ─────────────────────────────────────────────
echo "[1/4] Building and starting containers..."
docker compose -f docker-compose.hetzner.yml up -d --build
echo "      ✅ Containers started"

# ── 2. Wait for backend to be healthy ─────────────────────────────────────────
echo "[2/4] Waiting for backend to be ready (up to 90s)..."
for i in $(seq 1 30); do
  if docker exec olbostrade-backend curl -fsS http://127.0.0.1:8000/api/guardrails/status > /dev/null 2>&1; then
    echo "      ✅ Backend healthy"
    break
  fi
  if [[ $i -eq 30 ]]; then
    echo "      ❌ Backend did not start in time"
    echo "         Check logs: docker logs olbostrade-backend"
    exit 1
  fi
  sleep 3
done

# ── 3. Run database migrations ────────────────────────────────────────────────
echo "[3/4] Running database migrations..."
docker exec olbostrade-backend python3 -m alembic upgrade head
echo "      ✅ Migrations applied"

# ── 4. Add OlbosTrade to Caddy ────────────────────────────────────────────────
# NOTE: the host path and container name for the sibling Caddy stack have
# varied across servers/setups in practice. The values below are a best
# guess — if `docker exec olbos-caddy ...` fails, find the real ones with:
#   docker ps --format '{{.Names}}' | grep -i caddy
#   docker inspect <that-name> --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
echo "[4/4] Caddy configuration..."
CADDYFILE=/root/OlbosTerminal/docker/Caddyfile

if grep -q "olbostrade-backend" "$CADDYFILE" 2>/dev/null; then
  echo "      ✅ Caddy already configured for OlbosTrade"
else
  echo ""
  echo "  ⚠️  ACTION REQUIRED — update Caddy for the renamed containers:"
  echo ""
  echo "  Edit: $CADDYFILE"
  echo "  (if that path doesn't exist, see the NOTE above this section in"
  echo "  deploy/hetzner/up.sh for how to find the real one)"
  echo "  Replace any legacy backend/frontend container names with the"
  echo "  block below (replace trading.yourdomain.com with your subdomain):"
  echo ""
  cat deploy/hetzner/Caddyfile.snippet
  echo ""
  echo "  Then reload Caddy:"
  echo "    docker exec olbos-caddy caddy reload --config /etc/caddy/Caddyfile"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ OlbosTrade is running"
echo ""
echo "  Next: add the Caddyfile block above,"
echo "  point trading.yourdomain.com → this server's IP,"
echo "  then open https://trading.yourdomain.com"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
