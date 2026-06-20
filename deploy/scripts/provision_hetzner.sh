#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# OlbosQuant — Hetzner VPS Provisioning Script
#
# Run ONCE on a fresh Ubuntu 22.04/24.04 server as root.
#
# BEFORE RUNNING:
#   1. Create a Hetzner CX22+ (2 vCPU, 4GB RAM recommended)
#   2. SSH in: ssh root@YOUR_SERVER_IP
#   3. Run: bash provision_hetzner.sh
#
# FIREWALL (UFW):
#   Allows ONLY 22 (SSH), 80 (HTTP), 443 (HTTPS)
#   Does NOT expose 4002 (IB API) or 5900 (VNC) — use SSH tunnel for VNC
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

echo "═══════════════════════════════════════"
echo "  OlbosQuant — Hetzner Provisioning"
echo "═══════════════════════════════════════"

echo "[1/9] Updating system..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl wget git unzip \
    ca-certificates gnupg lsb-release \
    ufw fail2ban \
    htop ncdu

echo "[2/9] Creating deploy user..."
if ! id "deploy" &>/dev/null; then
    adduser --disabled-password --gecos "" deploy
    usermod -aG sudo deploy
    mkdir -p /home/deploy/.ssh
    if [ -f /root/.ssh/authorized_keys ]; then
        cp /root/.ssh/authorized_keys /home/deploy/.ssh/
        chown -R deploy:deploy /home/deploy/.ssh
        chmod 700 /home/deploy/.ssh
        chmod 600 /home/deploy/.ssh/authorized_keys
    fi
    echo "deploy ALL=(ALL) NOPASSWD: /usr/bin/docker" >> /etc/sudoers.d/deploy
fi

echo "[3/9] Installing Docker..."
if ! command -v docker &>/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    usermod -aG docker deploy
    systemctl enable docker
    systemctl start docker
fi
echo "  → Docker $(docker --version | cut -d' ' -f3 | tr -d ',')"

echo "[4/9] Configuring UFW firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp   comment 'SSH'
ufw allow 80/tcp   comment 'HTTP'
ufw allow 443/tcp  comment 'HTTPS'
ufw --force enable
echo "  → UFW: 22, 80, 443 only (4002/5900 NOT exposed)"

echo "[5/9] Configuring fail2ban..."
cat > /etc/fail2ban/jail.local << 'F2B'
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port    = ssh
logpath = %(sshd_log)s
backend = %(sshd_backend)s
F2B
systemctl enable fail2ban
systemctl restart fail2ban

echo "[6/9] Creating swap (2GB)..."
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl vm.swappiness=10
    echo 'vm.swappiness=10' >> /etc/sysctl.conf
fi

echo "[7/9] Enabling automatic security updates..."
apt-get install -y -qq unattended-upgrades
cat > /etc/apt/apt.conf.d/20auto-upgrades << 'UPGR'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
UPGR

echo "[8/9] Configuring Docker log rotation..."
mkdir -p /etc/docker
cat > /etc/docker/daemon.json << 'DOCKER'
{
    "log-driver": "json-file",
    "log-opts": {
        "max-size": "50m",
        "max-file": "5"
    }
}
DOCKER
systemctl restart docker

echo "[9/9] Creating app directory..."
mkdir -p /opt/olbosquant
chown deploy:deploy /opt/olbosquant

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✅ Hetzner provisioning complete!"
echo ""
echo "  NEXT STEPS:"
echo "  1. From your laptop, copy the repo + env:"
echo "     scp -r . deploy@YOUR_SERVER_IP:/opt/olbosquant/"
echo "     scp .env.hetzner deploy@YOUR_SERVER_IP:/opt/olbosquant/"
echo ""
echo "  2. SSH in and deploy:"
echo "     ssh deploy@YOUR_SERVER_IP"
echo "     cd /opt/olbosquant && bash deploy/scripts/deploy_hetzner.sh"
echo ""
echo "  3. Complete IBKR 2FA via VNC (SSH tunnel):"
echo "     ssh -L 5900:127.0.0.1:5900 deploy@YOUR_SERVER_IP"
echo "     open vnc://127.0.0.1:5900"
echo "═══════════════════════════════════════════════════════"
