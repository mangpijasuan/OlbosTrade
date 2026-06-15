#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# OlbosQuant — Hetzner Deploy / Update Script
#
# Run this on the Hetzner VPS as the deploy user from /opt/olbosquant.
#
# First deploy:
#   bash deploy/scripts/deploy_hetzner.sh --init
#
# Subsequent updates (after pushing code and rsync-ing to server):
#   bash deploy/scripts/deploy_hetzner.sh
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

COMPOSE="docker compose -f docker-compose.hetzner.yml"
DOMAIN="${DOMAIN:-}"   # set via env or passed in
INIT=${1:-}

echo "═══════════════════════════════════════════════"
echo "  OlbosQuant — Hetzner Deploy"
echo "═══════════════════════════════════════════════"

# ── Preflight checks ──────────────────────────────────────────────────────────
if [ ! -f .env.prod ]; then
    echo "ERROR: .env.prod not found in $(pwd)"
    echo "  cp .env.prod.hetzner.example .env.prod && fill in the values"
    exit 1
fi

# ── First-time SSL certificate issuance ──────────────────────────────────────
if [ "$INIT" = "--init" ]; then
    if [ -z "$DOMAIN" ]; then
        read -rp "Enter your domain (e.g. olbosquant.io): " DOMAIN
    fi

    echo "[init] Starting nginx on HTTP only for ACME challenge..."
    # Temporarily serve HTTP without SSL so certbot can verify domain
    $COMPOSE up -d nginx
    sleep 5

    echo "[init] Requesting Let's Encrypt certificate for $DOMAIN..."
    docker run --rm \
        -v "$(pwd)/certbot_certs:/etc/letsencrypt" \
        -v "$(pwd)/certbot_www:/var/www/certbot" \
        certbot/certbot certonly \
            --webroot \
            --webroot-path /var/www/certbot \
            --email "${ALERT_EMAIL:-admin@${DOMAIN}}" \
            --agree-tos \
            --no-eff-email \
            -d "$DOMAIN" \
            -d "www.$DOMAIN"

    # Patch nginx config with the real domain
    sed -i "s/YOUR_DOMAIN/$DOMAIN/g" deploy/nginx/olbosquant.conf
    echo "[init] nginx config patched with domain: $DOMAIN"
fi

# ── Build and start all services ──────────────────────────────────────────────
echo "[deploy] Building images..."
$COMPOSE build --pull

echo "[deploy] Starting services..."
$COMPOSE up -d

echo "[deploy] Running database migrations..."
$COMPOSE exec -T backend alembic upgrade head

echo "[deploy] Waiting for health checks..."
sleep 15

# ── Verify ────────────────────────────────────────────────────────────────────
BACKEND_STATUS=$(docker inspect --format='{{.State.Health.Status}}' olbosquant_backend 2>/dev/null || echo "unknown")
POSTGRES_STATUS=$(docker inspect --format='{{.State.Health.Status}}' olbosquant_postgres 2>/dev/null || echo "unknown")

echo ""
echo "═══════════════════════════════════════════════"
echo "  Deploy Status"
echo "  Backend   : $BACKEND_STATUS"
echo "  Postgres  : $POSTGRES_STATUS"
echo "  Frontend  : $(docker inspect --format='{{.State.Status}}' olbosquant_frontend 2>/dev/null || echo unknown)"
echo "  Nginx     : $(docker inspect --format='{{.State.Status}}' olbosquant_nginx 2>/dev/null || echo unknown)"
echo ""
if [ -n "$DOMAIN" ]; then
    echo "  URL: https://$DOMAIN"
fi
echo "  API docs: http://localhost:8000/docs (from server)"
echo "═══════════════════════════════════════════════"
