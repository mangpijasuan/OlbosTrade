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

# docker_default is declared `external: true` in the compose file, so Compose
# will NOT create it — it errors out instead. It is external on purpose:
# ibkr-gateway belongs to a separate compose project and sits on this network,
# and IBKR_HOST=ibkr-gateway resolves over it, so `docker compose down` here
# must never remove it.
#
# It used to be created by the OlbosTerminal stack. That application has been
# deleted, so nothing recreates it if it is ever removed — hence creating it
# here rather than telling the operator to start a project that no longer
# exists, which is what this block said until 2026-09-19.
if ! docker network ls --format '{{.Name}}' | grep -qE '^docker_default$'; then
  echo "      docker_default missing — creating it"
  docker network create docker_default
fi
echo "      Using network: docker_default"

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

# ── 4. Confirm Caddy is serving ───────────────────────────────────────────────
# Nothing to paste any more: deploy/hetzner/Caddyfile is a tracked file in this
# repo, mounted read-only into the `caddy` service by the compose file above.
# Until 2026-09-19 this step printed a snippet for the operator to copy into a
# different project's Caddyfile, which is why the config and the app could
# disagree at all.
echo "[4/4] Checking Caddy..."
if docker exec olbostrade-caddy caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
  echo "      ✅ Caddy running with a valid config"
else
  echo "      ⚠️  Caddy is not running, or its config did not validate."
  echo "         docker logs olbostrade-caddy --tail 50"
  echo "         Reload after fixing deploy/hetzner/Caddyfile in git:"
  echo "           docker exec olbostrade-caddy caddy reload --config /etc/caddy/Caddyfile"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ OlbosTrade is running"
echo ""
echo "  Next: point trade.olbos.us → this server's IP"
echo "  (DNS-only — disable any CDN proxy, ACME must reach this host),"
echo "  then open https://trade.olbos.us"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
