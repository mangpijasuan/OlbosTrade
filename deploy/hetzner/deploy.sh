#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/olbosquant}"
ENV_FILE="${APP_DIR}/.env.hetzner"
COMPOSE_FILE="${APP_DIR}/docker-compose.hetzner.yml"

cd "${APP_DIR}"

if [ ! -f "${ENV_FILE}" ]; then
  echo "Missing ${ENV_FILE}. Create it from deploy/hetzner/env.hetzner.example." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

GHCR_IMAGE_PREFIX="${DEPLOY_GHCR_IMAGE_PREFIX:-${GHCR_IMAGE_PREFIX:-}}"
IMAGE_TAG="${DEPLOY_IMAGE_TAG:-${IMAGE_TAG:-latest}}"
GHCR_USERNAME="${DEPLOY_GHCR_USERNAME:-${GHCR_USERNAME:-}}"
GHCR_TOKEN="${DEPLOY_GHCR_TOKEN:-${GHCR_TOKEN:-}}"

if [ -z "${DOMAIN:-}" ]; then
  echo "DOMAIN is required in ${ENV_FILE}" >&2
  exit 1
fi
if [ -z "${GHCR_IMAGE_PREFIX:-}" ]; then
  echo "GHCR_IMAGE_PREFIX is required in ${ENV_FILE}" >&2
  exit 1
fi

export GHCR_IMAGE_PREFIX IMAGE_TAG

if [ -n "${GHCR_USERNAME:-}" ] && [ -n "${GHCR_TOKEN:-}" ]; then
  echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USERNAME}" --password-stdin
fi

if [ ! -f "/var/lib/docker/volumes/olbosquant_certbot_certs/_data/live/${DOMAIN}/fullchain.pem" ]; then
  echo "Bootstrapping temporary self-signed certificate for ${DOMAIN}"
  docker volume create olbosquant_certbot_certs >/dev/null
  docker run --rm \
    -v olbosquant_certbot_certs:/etc/letsencrypt \
    alpine:3.20 sh -c "\
      apk add --no-cache openssl >/dev/null && \
      mkdir -p /etc/letsencrypt/live/${DOMAIN} && \
      openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
        -keyout /etc/letsencrypt/live/${DOMAIN}/privkey.pem \
        -out /etc/letsencrypt/live/${DOMAIN}/fullchain.pem \
        -subj '/CN=${DOMAIN}'"
fi

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" pull
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d postgres redis ib-gateway
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d backend frontend nginx

echo "Running database migrations"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" exec -T backend alembic upgrade head || {
  echo "Migration failed. Inspect backend logs before enabling trading." >&2
  exit 1
}

if [ -n "${CERTBOT_EMAIL:-}" ]; then
  echo "Requesting/renewing Let's Encrypt certificate for ${DOMAIN}"
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" run --rm certbot certonly \
    --webroot -w /var/www/certbot \
    --email "${CERTBOT_EMAIL}" --agree-tos --no-eff-email \
    -d "${DOMAIN}" -d "www.${DOMAIN}" || true
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" restart nginx
fi

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d certbot
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps
