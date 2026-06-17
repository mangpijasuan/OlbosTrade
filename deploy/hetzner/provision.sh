#!/usr/bin/env bash
set -euo pipefail

# One-time setup for an Ubuntu Hetzner server.
# Run as root after creating the server:
#   curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/deploy/hetzner/provision.sh | bash

DEPLOY_USER="${DEPLOY_USER:-deploy}"
APP_DIR="${APP_DIR:-/opt/olbosquant}"

echo "[1/7] Updating packages"
apt-get update
apt-get upgrade -y

echo "[2/7] Installing base packages"
apt-get install -y ca-certificates curl git gnupg ufw fail2ban rsync

echo "[3/7] Installing Docker"
install -m 0755 -d /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
fi
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "[4/7] Creating deploy user"
if ! id "${DEPLOY_USER}" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "${DEPLOY_USER}"
fi
usermod -aG docker "${DEPLOY_USER}"
mkdir -p "/home/${DEPLOY_USER}/.ssh"
if [ -f /root/.ssh/authorized_keys ]; then
  cp /root/.ssh/authorized_keys "/home/${DEPLOY_USER}/.ssh/authorized_keys"
fi
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "/home/${DEPLOY_USER}/.ssh"
chmod 700 "/home/${DEPLOY_USER}/.ssh"
chmod 600 "/home/${DEPLOY_USER}/.ssh/authorized_keys" 2>/dev/null || true

echo "[5/7] Creating app directory"
mkdir -p "${APP_DIR}/deploy/hetzner" "${APP_DIR}/deploy/nginx"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${APP_DIR}"

echo "[6/7] Configuring firewall"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "[7/7] Enabling Docker"
systemctl enable --now docker

cat <<EOF

Hetzner provision complete.

Next:
1. Point your DNS A record at this server.
2. Copy .env.hetzner to ${APP_DIR}/.env.hetzner.
3. Add GitHub repo secrets for deployment.
4. Trigger the GitHub Actions deploy workflow.

For IB Gateway login/VNC:
  ssh -L 5900:127.0.0.1:5900 ${DEPLOY_USER}@YOUR_SERVER_IP
  then open vnc://127.0.0.1:5900 and complete IBKR 2FA on the server gateway.
EOF
