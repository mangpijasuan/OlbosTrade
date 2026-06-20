# Deploy OlbosQuant on Hetzner (IBKR options, no laptop)

Run the full stack on a Hetzner VPS: **headless IB Gateway + backend + UI**. Your Mac is only needed for occasional **2FA via VNC** when the gateway restarts.

## Architecture

```
Hetzner VPS
├── ib-gateway (Docker)     socket :4002 — internal only
│                             VNC :5900  — localhost + SSH tunnel
├── backend (FastAPI)
├── postgres + redis
├── frontend (React build)
└── nginx (:80 public)
```

| Port | Public? | Purpose |
|------|---------|---------|
| 80 | ✅ | UI + API |
| 443 | ✅ optional | HTTPS (add later) |
| 4002 | ❌ | IB API — Docker network only |
| 5900 | ❌ | VNC — SSH tunnel only |
| 8000 | ❌ | Backend — nginx proxy only |

## Requirements

- Hetzner **CX22** or larger (2 vCPU, 4GB RAM)
- Ubuntu 22.04/24.04
- IBKR **paper** username + password
- Phone for **IBKR Key** 2FA when gateway restarts

## 1. Provision the server (once)

```bash
ssh root@YOUR_SERVER_IP
curl -fsSL https://raw.githubusercontent.com/mangpijasuan/OlbosQuant/main/deploy/scripts/provision_hetzner.sh | bash
```

Or clone the repo and run `bash deploy/scripts/provision_hetzner.sh`.

## 2. Configure secrets (on your laptop)

```bash
cp .env.hetzner.example .env.hetzner
```

Fill in:

```env
IBKR_USERNAME=your_paper_username
IBKR_PASSWORD=your_paper_password
IBKR_TRADING_MODE=paper
POSTGRES_PASSWORD=strong_random_password
SECRET_KEY=$(openssl rand -hex 32)
VNC_PASSWORD=choose_a_vnc_password
```

## 3. Copy app to server

```bash
rsync -av --exclude node_modules --exclude .git \
  ./ deploy@YOUR_SERVER_IP:/opt/olbosquant/

scp .env.hetzner deploy@YOUR_SERVER_IP:/opt/olbosquant/
```

## 4. Deploy

```bash
ssh deploy@YOUR_SERVER_IP
cd /opt/olbosquant
chmod +x deploy/scripts/deploy_hetzner.sh
bash deploy/scripts/deploy_hetzner.sh
```

## 5. Complete IBKR 2FA (VNC over SSH)

IB Gateway will start but needs **2FA approval** on first boot (and after daily restart).

**Terminal on your Mac:**

```bash
ssh -L 5900:127.0.0.1:5900 deploy@YOUR_SERVER_IP
```

**New tab — open VNC:**

```bash
open vnc://127.0.0.1:5900
```

Password = `VNC_PASSWORD` from `.env.hetzner`.

In the VNC window:

1. Log in to **IB Gateway (paper)** if prompted
2. Approve **2FA** on your phone when asked
3. Confirm API is enabled (port **4002**)

## 6. Verify

```bash
# On the server
curl -s http://localhost/api/market/broker | python3 -m json.tool
curl -s http://localhost/health
```

Expected:

```json
{
  "broker": "ibkr",
  "paper_mode": true,
  "status": "connected"
}
```

Open in browser: `http://YOUR_SERVER_IP/`

## Daily / weekly ops

| Task | How often | Action |
|------|-----------|--------|
| 2FA after gateway restart | ~daily | VNC + phone approve |
| Check broker | daily | `curl localhost/api/market/broker` |
| Logs | as needed | `docker compose -f docker-compose.hetzner.yml logs -f backend` |
| Update app | on release | `git pull && bash deploy/scripts/deploy_hetzner.sh` |

## Commands cheat sheet

```bash
# Status
docker compose -f docker-compose.hetzner.yml ps

# Logs
docker compose -f docker-compose.hetzner.yml logs -f ib-gateway backend

# Restart stack
docker compose -f docker-compose.hetzner.yml --env-file .env.hetzner restart

# Stop
docker compose -f docker-compose.hetzner.yml down

# Rebuild after code changes
docker compose -f docker-compose.hetzner.yml --env-file .env.hetzner up -d --build
```

## Security notes

- **Never** expose ports 4002 or 5900 in Hetzner firewall or `docker-compose` public bindings
- Restrict UI access: Hetzner firewall → allow your home IP only on port 80, or add HTTP basic auth in nginx
- Use SSH keys, disable password SSH
- `.env.hetzner` contains IBKR password — never commit it

## HTTPS (optional)

1. Point a domain A-record to your server IP
2. Replace `deploy/nginx/hetzner-http.conf` with `olbosquant.conf` + certbot (see `docker-compose.prod.yml`)
3. Open port 443 in UFW

## Alpaca alternative (no options)

If you only need equities and want zero 2FA:

```env
BROKER=alpaca
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

Remove `ib-gateway` from compose or leave it stopped. **Options trading will not work** — the app raises `NotImplementedError` for options on Alpaca.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `broker: disconnected` | VNC in, complete 2FA; check `docker logs olbosquant_ib_gateway` |
| Gateway restart loop | Wrong password; competing IBKR session elsewhere — log out TWS/mobile |
| Backend won't start | `docker logs olbosquant_backend`; check `POSTGRES_PASSWORD` |
| UI loads, API 502 | `docker compose ps` — wait for backend healthy |
| `Address already in use` 4002 | Only one ib-gateway instance; `docker compose down` first |

## Local vs Hetzner

| | Mac (now) | Hetzner |
|--|-----------|---------|
| IB Gateway | Native app | Docker headless |
| 2FA | Gateway window | VNC + SSH tunnel |
| Laptop required | Yes | No (phone 2FA only) |
| Options | ✅ | ✅ |
