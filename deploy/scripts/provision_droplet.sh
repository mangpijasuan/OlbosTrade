#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# OlbosQuant — DigitalOcean Droplet Provisioning Script
#
# Run this ONCE on a fresh Ubuntu 22.04 Droplet after SSH'ing in as root.
#
# BEFORE RUNNING:
#   1. Create a $24/mo Droplet (2 vCPU, 4GB RAM, Ubuntu 22.04 LTS)
#   2. SSH in: ssh root@YOUR_DROPLET_IP
#   3. Run: bash provision_droplet.sh
#
# WHAT IT DOES:
#   - Creates a non-root deploy user
#   - Installs Docker + Docker Compose
#   - Installs DO CLI (doctl) for registry auth
#   - Configures UFW firewall (80, 443, 22 only)
#   - Sets up automatic security updates
#   - Creates swap space (safety net for 4GB RAM)
#   - Configures log rotation
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

echo "═══════════════════════════════════════"
echo "  OlbosQuant — Droplet Provisioning"
echo "═══════════════════════════════════════"

# ── 1. System update ──────────────────────────────────────────────────────────
echo "[1/10] Updating system..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl wget git unzip \
    ca-certificates gnupg lsb-release \
    ufw fail2ban \
    htop ncdu

# ── 2. Create deploy user ─────────────────────────────────────────────────────
echo "[2/10] Creating deploy user..."
if ! id "deploy" &>/dev/null; then
    adduser --disabled-password --gecos "" deploy
    usermod -aG sudo deploy
    mkdir -p /home/deploy/.ssh
    cp /root/.ssh/authorized_keys /home/deploy/.ssh/
    chown -R deploy:deploy /home/deploy/.ssh
    chmod 700 /home/deploy/.ssh
    chmod 600 /home/deploy/.ssh/authorized_keys
    echo "deploy ALL=(ALL) NOPASSWD: /usr/bin/docker, /usr/local/bin/docker-compose" \
        >> /etc/sudoers.d/deploy
fi
echo "  → deploy user created"

# ── 3. Install Docker ─────────────────────────────────────────────────────────
echo "[3/10] Installing Docker..."
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

# ── 4. Install doctl (DigitalOcean CLI) ───────────────────────────────────────
echo "[4/10] Installing doctl..."
if ! command -v doctl &>/dev/null; then
    DOCTL_VERSION=$(curl -s https://api.github.com/repos/digitalocean/doctl/releases/latest \
        | grep '"tag_name"' | cut -d'"' -f4 | tr -d 'v')
    wget -q "https://github.com/digitalocean/doctl/releases/download/v${DOCTL_VERSION}/doctl-${DOCTL_VERSION}-linux-amd64.tar.gz"
    tar xf "doctl-${DOCTL_VERSION}-linux-amd64.tar.gz"
    mv doctl /usr/local/bin/
    rm -f "doctl-${DOCTL_VERSION}-linux-amd64.tar.gz"
fi
echo "  → doctl $(doctl version | head -1)"

# ── 5. Firewall ───────────────────────────────────────────────────────────────
echo "[5/10] Configuring UFW firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    comment 'SSH'
ufw allow 80/tcp    comment 'HTTP'
ufw allow 443/tcp   comment 'HTTPS'
ufw --force enable
echo "  → UFW enabled: ports 22, 80, 443"

# ── 6. Fail2ban ───────────────────────────────────────────────────────────────
echo "[6/10] Configuring fail2ban..."
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
echo "  → fail2ban configured (SSH brute-force protection)"

# ── 7. Swap space ─────────────────────────────────────────────────────────────
echo "[7/10] Creating 2GB swap..."
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl vm.swappiness=10
    echo 'vm.swappiness=10' >> /etc/sysctl.conf
fi
echo "  → 2GB swap active"

# ── 8. Automatic security updates ────────────────────────────────────────────
echo "[8/10] Enabling unattended security upgrades..."
apt-get install -y -qq unattended-upgrades
cat > /etc/apt/apt.conf.d/20auto-upgrades << 'UPGR'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
UPGR
echo "  → Automatic security updates enabled"

# ── 9. Log rotation for Docker ────────────────────────────────────────────────
echo "[9/10] Configuring Docker log rotation..."
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
echo "  → Docker log rotation configured"

# ── 10. App directory ─────────────────────────────────────────────────────────
echo "[10/10] Creating app directory..."
mkdir -p /opt/olbosquant
chown deploy:deploy /opt/olbosquant
echo "  → /opt/olbosquant created"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  ✅ Provisioning complete!"
echo ""
echo "  NEXT STEPS:"
echo "  1. Authenticate doctl:"
echo "     doctl auth init"
echo ""
echo "  2. Log into DO Container Registry:"
echo "     doctl registry login"
echo ""
echo "  3. Copy your .env.prod to the server:"
echo "     scp .env.prod deploy@YOUR_DROPLET_IP:/opt/olbosquant/"
echo ""
echo "  4. Run the deploy script:"
echo "     ssh deploy@YOUR_DROPLET_IP"
echo "     cd /opt/olbosquant && bash deploy.sh"
echo "═══════════════════════════════════════════════════════"
