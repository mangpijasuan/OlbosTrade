#!/bin/bash
# Deploy OlbosQuant on Hetzner (build + start all services)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

ENV_FILE="${ENV_FILE:-.env.hetzner}"

if [ ! -f "$ENV_FILE" ]; then
  echo "❌ Missing $ENV_FILE"
  echo "   cp .env.hetzner.example .env.hetzner && fill in secrets"
  exit 1
fi

# Require critical secrets
missing=0
for key in IBKR_USERNAME IBKR_PASSWORD POSTGRES_PASSWORD SECRET_KEY; do
  if ! grep -qE "^${key}=.+" "$ENV_FILE" 2>/dev/null; then
    echo "❌ $ENV_FILE: $key is empty"
    missing=1
  fi
done
[ "$missing" -eq 0 ] || exit 1

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  OlbosQuant — Hetzner Deploy"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "[1/4] Pulling ib-gateway image..."
docker compose -f docker-compose.hetzner.yml --env-file "$ENV_FILE" pull ib-gateway

echo "[2/4] Building backend + frontend..."
docker compose -f docker-compose.hetzner.yml --env-file "$ENV_FILE" build backend frontend

echo "[3/4] Starting stack..."
docker compose -f docker-compose.hetzner.yml --env-file "$ENV_FILE" up -d

echo "[4/4] Waiting for backend health..."
for i in $(seq 1 60); do
  if curl -sf http://localhost/health > /dev/null 2>&1; then
    echo "✅ Backend healthy"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "⚠️  Backend not healthy yet — check: docker compose -f docker-compose.hetzner.yml logs backend"
  fi
  sleep 2
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Stack is up"
echo ""
echo "  UI:     http://$(curl -s ifconfig.me 2>/dev/null || echo YOUR_SERVER_IP)/"
echo "  Health: http://$(curl -s ifconfig.me 2>/dev/null || echo YOUR_SERVER_IP)/health"
echo ""
echo "  IBKR 2FA (first boot / daily):"
echo "    ssh -L 5900:127.0.0.1:5900 deploy@YOUR_SERVER_IP"
echo "    open vnc://127.0.0.1:5900"
echo ""
echo "  Broker status:"
echo "    curl -s http://localhost/api/market/broker | python3 -m json.tool"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
