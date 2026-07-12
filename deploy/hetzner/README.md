# OlbosTrade — Deploy on Hetzner (alongside olbos app)

Runs OlbosTrade on the **same Hetzner server** as the olbos app.
Caddy (already running in olbos) handles HTTPS for both — no second reverse proxy needed.

## Architecture

```
Internet
    │
    ▼
 Caddy (olbos-caddy container, ports 80/443)
    ├── olbos.yourdomain.com      → olbos-backend / olbos-frontend
    └── trading.yourdomain.com   → olbostrade-backend / olbostrade-frontend
                                       │
                                  olbostrade-db (postgres)
                                  olbostrade-redis
```

OlbosTrade joins the `olbos_default` Docker network so Caddy can reach it.
Its database and Redis are isolated on `olbostrade_internal` — separate from olbos.

NOTE: the Postgres database itself keeps its original name/user/data volume
(`olbosquantdb` / `olbosquant` / `olbosquant_pgdata`) — only the Docker
container, network, and directory names were rebranded. See the comment at
the top of `docker-compose.hetzner.yml` for why.

---

## First deploy (do this once)

### 1. SSH into the server
```bash
ssh root@<YOUR_HETZNER_IP>
```

### 2. Clone OlbosTrade
```bash
cd /opt
git clone https://github.com/mangpijasuan/OlbosTrade.git olbostrade
cd olbostrade
```

### 3. Create the env file
```bash
cp deploy/hetzner/.env.example backend/.env.prod
nano backend/.env.prod
```

Fill in these required values:
| Variable | How to get it |
|----------|--------------|
| `OLBOSQUANT_DB_PASSWORD` | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `OLBOS_API_KEY` | `python3 -c "import secrets; print(secrets.token_hex(32))"` |

`OLBOSQUANT_DB_PASSWORD` keeps its original name (matches the unchanged
Postgres user/db — see the note above); it is NOT `OLBOSTRADE_DB_PASSWORD`.

Leave `DATABASE_URL` and `REDIS_URL` blank — docker-compose fills them in.

### 4. Add a DNS record

At your domain registrar, add an A record:
```
trading.yourdomain.com  →  <YOUR_HETZNER_IP>
```

Wait ~60 seconds for DNS to propagate.

### 5. Start OlbosTrade
```bash
bash deploy/hetzner/up.sh
```

The script will:
- Build and start all containers
- Run database migrations
- Print the Caddyfile block you need to add

### 6. Add OlbosTrade to Caddy

The script prints exactly what to add. Manually:
```bash
nano /opt/olbosterminal/docker/Caddyfile
```

Add the block from `deploy/hetzner/Caddyfile.snippet` (replace `trading.yourdomain.com`).

Then reload Caddy (no downtime for the olbos app):
```bash
docker exec olbosterminal-caddy caddy reload --config /etc/caddy/Caddyfile
```

### 7. Verify
```bash
curl -s https://trading.yourdomain.com/api/guardrails/status
# → {"trading_allowed":true,"trading_mode":"normal",...}
```

Open **https://trading.yourdomain.com** in your browser.

---

## Updating after a code change

```bash
cd /opt/olbostrade
bash deploy/hetzner/update.sh
```

This pulls latest code, rebuilds, restarts, and runs any new migrations.

---

## Useful commands

```bash
# View live logs
docker logs olbostrade-backend -f
docker logs olbostrade-frontend -f

# Check all container status
docker compose -f docker-compose.hetzner.yml ps

# Stop everything (does not delete data)
docker compose -f docker-compose.hetzner.yml down

# Open a shell in backend
docker exec -it olbostrade-backend bash

# Run a migration manually
docker exec olbostrade-backend python3 -m alembic upgrade head

# Check database (user/db name unchanged — see note above)
docker exec -it olbostrade-db psql -U olbosquant -d olbosquantdb
```

---

## IBKR Gateway (Docker)

OlbosTrade talks to IBKR through the [gnzsnz/ib-gateway](https://github.com/gnzsnz/ib-gateway-docker) image via `ib_insync` (socket API, not Client Portal).

### Start the gateway (same server)

```bash
docker run -d --name ibkr-gateway --restart unless-stopped \
  --network docker_default \
  -e TWS_USERID=your_ibkr_username \
  -e TWS_PASSWORD=your_ibkr_password \
  -e TRADING_MODE=paper \
  -e GATEWAY_OR_TWS=gateway \
  -e READ_ONLY_API=no \
  -e TWOFA_TIMEOUT_ACTION=restart \
  -e EXISTING_SESSION_DETECTED_ACTION=primaryoverride \
  -e TRUSTED_IPS=127.0.0.1,172.18.0.0/16 \
  -p 4002:4004 \
  -v ibkr-gateway_ibkr_settings:/home/ibgateway/Jts \
  ghcr.io/gnzsnz/ib-gateway:stable
```

Important:

| Setting | Value | Why |
|---------|-------|-----|
| `IBKR_HOST` | `ibkr-gateway` | Docker DNS on `docker_default` network |
| `IBKR_PORT` | `4004` | gnzsnz **socat** publishes paper API on container port **4004** (not 4002) |
| Host port map | `4002:4004` | Host clients use 4002; in-network clients use 4004 |
| Workers | `1` | IBKR allows only one connection per `IBKR_CLIENT_ID` |

After gateway restart, approve **2FA** on the IBKR mobile app if prompted. Check logs:

```bash
docker logs ibkr-gateway --tail 30    # expect "Login has completed"
docker logs olbostrade-backend --tail 20   # expect "Broker connected successfully"
```

Test from the backend container:

```bash
docker exec olbostrade-backend python3 -c "
import asyncio, os
from ib_insync import IB
async def t():
    ib = IB()
    await ib.connectAsync('ibkr-gateway', int(os.environ['IBKR_PORT']), clientId=99, timeout=20)
    print('accounts', ib.managedAccounts())
    ib.disconnect()
asyncio.run(t())
"
```

---

## RAM usage estimate

| Container | RAM |
|-----------|-----|
| olbostrade-backend | ~400–800 MB |
| olbostrade-frontend | ~100 MB |
| olbostrade-db | ~150–300 MB |
| olbostrade-redis | ~50 MB |
| **Total** | **~700 MB – 1.3 GB** |

Your existing olbos app uses ~2–3 GB.
A **CX32 (8 GB RAM, ~€17/mo)** comfortably runs both.
If your server is already 8 GB, upgrade to CX32 before deploying.
