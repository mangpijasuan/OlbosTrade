#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# OlbosQuant — Hetzner VPS Provisioning Script
#
# Run ONCE on a fresh Hetzner Cloud server (Ubuntu 22.04, CX21 or larger).
#
# BEFORE RUNNING:
#   1. Create a Hetzner Cloud server:
#      - Type: CX21 (2 vCPU, 4GB RAM) — minimum; CX31 (8GB) recommended
#      - Image: Ubuntu 22.04
#      - Add your SSH key
#   2. SSH in: ssh root@YOUR_SERVER_IP
#   3. Run: bash provision_hetzner.sh
#
# WHAT IT DOES:
#   - Creates a non-root deploy user
#   - Installs Docker + Docker Compose plugin
#   - Configures UFW firewall (22, 80, 443 only)
#   - Sets up fail2ban (SSH brute-force protection)
#   - Creates 2GB swap (safety net)
#   - Enables automatic security updates
#   - Clones the repo to /opt/olbosquant
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

echo "═══════════════════════════════════════════════"
echo "  OlbosQuant — Hetzner VPS Provisioning"
echo "═══════════════════════════════════════════════"

# ── 1. System update ──────────────────────────────────────────────────────────
echo "[1/9] Updating system..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
apt-get install -y -qq \
    curl wget git unzip \
    ca-certificates gnupg lsb-release \
    ufw fail2ban \
    htop ncdu netcat-openbsd

# ── 2. Create deploy user ─────────────────────────────────────────────────────
echo "[2/9] Creating deploy user..."
if ! id "deploy" &>/dev/null; then
    adduser --disabled-password --gecos "" deploy
    usermod -aG sudo deploy
    mkdir -p /home/deploy/.ssh
    cp /root/.ssh/authorized_keys /home/deploy/.ssh/ 2>/dev/null || true
    chown -R deploy:deploy /home/deploy/.ssh
    chmod 700 /home/deploy/.ssh
    chmod 600 /home/deploy/.ssh/authorized_keys 2>/dev/null || true
    echo "deploy ALL=(ALL) NOPASSWD: /usr/bin/docker, /usr/local/bin/docker" \
        >> /etc/sudoers.d/deploy-docker
    chmod 440 /etc/sudoers.d/deploy-docker
fi
echo "  → deploy user ready"

# ── 3. Install Docker ─────────────────────────────────────────────────────────
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

# ── 4. Configure Docker log rotation ─────────────────────────────────────────
echo "[4/9] Configuring Docker log rotation..."
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
echo "  → Log rotation configured"

# ── 5. Firewall ───────────────────────────────────────────────────────────────
echo "[5/9] Configuring UFW firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    comment 'SSH'
ufw allow 80/tcp    comment 'HTTP'
ufw allow 443/tcp   comment 'HTTPS'
ufw --force enable
echo "  → UFW: ports 22, 80, 443 open"

# ── 6. fail2ban ───────────────────────────────────────────────────────────────
echo "[6/9] Configuring fail2ban..."
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
echo "  → fail2ban active"

# ── 7. Swap space ─────────────────────────────────────────────────────────────
echo "[7/9] Creating 2GB swap..."
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo 'vm.swappiness=10' >> /etc/sysctl.conf
    sysctl -p
fi
echo "  → 2GB swap active"

# ── 8. Automatic security updates ────────────────────────────────────────────
echo "[8/9] Enabling unattended security upgrades..."
apt-get install -y -qq unattended-upgrades
cat > /etc/apt/apt.conf.d/20auto-upgrades << 'UPGR'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
UPGR
echo "  → Automatic security updates enabled"

# ── 9. App directory ─────────────────────────────────────────────────────────
echo "[9/9] Creating app directory..."
mkdir -p /opt/olbosquant
chown deploy:deploy /opt/olbosquant
echo "  → /opt/olbosquant ready"

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ✅ Hetzner VPS provisioned!"
echo ""
echo "  NEXT STEPS on your LOCAL machine:"
echo ""
echo "  1. Point your domain DNS A record → $(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_SERVER_IP')"
echo ""
echo "  2. Copy the repo and config to the server:"
echo "     scp .env.prod deploy@$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_SERVER_IP'):/opt/olbosquant/"
echo "     rsync -avz --exclude='.git' --exclude='node_modules' \\"
echo "       . deploy@$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_SERVER_IP'):/opt/olbosquant/"
echo ""
echo "  3. SSH in and run the deploy script:"
echo "     ssh deploy@$(curl -s ifconfig.me 2>/dev/null || echo 'YOUR_SERVER_IP')"
echo "     cd /opt/olbosquant && bash deploy/scripts/deploy_hetzner.sh"
echo "═══════════════════════════════════════════════════════════════"
