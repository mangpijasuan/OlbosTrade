# OlbosTrade — Deploy on Hetzner (alongside olbos app)

Runs OlbosTrade on the **same Hetzner server** as the olbos app.
Caddy (already running in olbos) handles HTTPS for both — no second reverse proxy needed.

## Architecture

```
Internet
    │
    ▼
 Caddy (olbos-caddy container, ports 80/443)
    ├── olbos.<the other app>     → olbos-backend / olbos-frontend
    └── trade.olbos.us          → olbostrade-backend / olbostrade-frontend
                                       │
                                  olbostrade-db (postgres)
                                  olbostrade-redis
```

OlbosTrade joins the `olbos_default` Docker network so Caddy can reach it.
Its database and Redis are isolated on `olbostrade_internal` — separate from olbos.

NOTE: the Postgres database is `olbostrade`; the role stays `olbosquant`
deliberately (see the Migration section below for why). Docker container,
network, and directory names are fully rebranded.

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
| `OLBOSTRADE_DB_PASSWORD` | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `OLBOS_API_KEY` | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `TRUSTED_PROXY_SECRET` | `openssl rand -hex 32` |

`TRUSTED_PROXY_SECRET` is a shared secret between nginx and the backend, and
the stack will not start without it — `docker-compose.hetzner.yml` declares it
`${TRUSTED_PROXY_SECRET:?...}`, so Compose aborts rather than booting into a
state where the login rate limiter cannot tell callers apart. nginx stamps it
onto every proxied request; the backend honours `X-Forwarded-For` only when
that header matches, and otherwise falls back to the socket peer. It has to be
set on BOTH the backend and frontend services, which the compose file already
does from this one variable — set it once here.

`OLBOSTRADE_DB_PASSWORD` is the database password variable referenced by
`docker-compose.hetzner.yml` — it authenticates as the `olbosquant` role
(kept deliberately; see "Migration" below) against the `olbostrade`
database. The password value itself is unchanged from before the rename.

Leave `DATABASE_URL` and `REDIS_URL` blank — docker-compose fills them in.

### 3b. Before you point a public name at this — check it needs a password

```bash
grep -E '^(DASH_USER|DASH_PASS|AUTH_ENABLED)=' backend/.env.prod
```

Until now this instance has been reachable only as an unadvertised `IP:8080`,
which is obscurity, not access control. A domain removes even that.

**Both** `DASH_USER` *and* `DASH_PASS` must be non-empty. The entrypoint gates
on `[ -n "$DASH_USER" ] && [ -n "$DASH_PASS" ]` — set only one and Basic Auth
is silently off while the config *looks* filled in. Treat exactly-one-set as a
failed check, not a partial win.

If Basic Auth is off **and** `AUTH_ENABLED` is false, the frontend serves the
whole terminal — kill switch, position closing, execution mode — to anyone who
resolves the name. Confirm which state you are in from the container's own
report rather than from the env file:

```bash
docker logs olbostrade-frontend 2>&1 | grep -iE "Dashboard auth|DASH_USER"
```

`Dashboard auth ENABLED` means both were set. The `WARNING: DASH_USER/DASH_PASS
not set` line means the app is open — including when you filled in one of them.

Set one of these first:

* `DASH_USER`/`DASH_PASS` put nginx Basic Auth in front of everything,
  including `/api` (see `frontend/docker-entrypoint.sh`). Simplest.
* `AUTH_ENABLED=true` uses real accounts from `scripts/create_user.py`.

These are not interchangeable with `SECRET_KEY`. That one guards *mutating*
API routes and is entered per-session in the browser; it does nothing to stop
someone reading the terminal, and the kill-switch engage route deliberately
does not require it at all.

### 4. Add a DNS record

At your domain registrar, add an A record:
```
trade.olbos.us  →  <YOUR_HETZNER_IP>
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
nano /root/OlbosTerminal/docker/Caddyfile
```

If that path doesn't exist on your server, find the real one — the host
path and container name for the sibling Caddy stack are NOT guaranteed to
match the docs (verified the hard way during the Hetzner infra migration):
```bash
docker ps --format '{{.Names}}' | grep -i caddy
docker inspect <name-from-above> --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
```

Add the block from `deploy/hetzner/Caddyfile.snippet` verbatim — it already
names `trade.olbos.us`.

Caddy obtains its certificate over the ACME **HTTP** challenge, so port 80
must be reachable. UFW is active on this host; check with `ufw status`.

Then reload Caddy (no downtime for the olbos app):
```bash
docker exec olbos-caddy caddy reload --config /etc/caddy/Caddyfile
```

### 7. Verify
```bash
curl -s https://trade.olbos.us/api/guardrails/status
# → {"trading_allowed":true,"trading_mode":"normal",...}
```

Open **https://trade.olbos.us** in your browser.

**Without a domain**, the frontend is also published directly on the host at
port **8080** — `http://<YOUR_HETZNER_IP>:8080`, terminal at
`http://<YOUR_HETZNER_IP>:8080/terminal`.

> ⚠️ **That path is plain HTTP. Do not enter the Operator API Key over it.**
> The key is your `SECRET_KEY`, it authorises closing positions and changing
> execution mode, and on `http://` it crosses the network in clear text. The
> same port serves without Basic Auth unless **both** `DASH_USER` and
> `DASH_PASS` are set — one alone leaves it open (see step 3b) — so treat it as
> read-only triage: useful for confirming the stack is up during an incident,
> not for operating it.
>
> Now that `https://trade.olbos.us` exists, use it — it is the correct answer
> to this, and step 7b closes `:8080` entirely. If the domain is unavailable,
> tunnel instead:
> ```bash
> ssh -L 8080:localhost:8080 root@<YOUR_HETZNER_IP>
> # then open http://localhost:8080 — traffic rides the SSH tunnel
> ``` That number comes from the
`ports: ["8080:3000"]` entry on the `frontend` service in
`docker-compose.hetzner.yml`; if you change it there, change it here. The
backend is NOT published to the host — it is reachable only over the internal
Docker network, which is why `curl localhost:8000` on the server returns
nothing and `docker exec olbostrade-backend curl localhost:8000/health` works.

### 7b. Close the direct HTTP port

Once HTTPS works, the published `:8080` is no longer needed — Caddy reaches the
frontend over the Docker network, not the host port.

> **`ufw deny 8080` does NOT close it.** Docker publishes ports with its own
> DNAT and FORWARD rules, which are traversed before UFW's, so a published
> container port stays reachable from the internet no matter what `ufw status`
> says. An earlier revision of this guide recommended exactly that, which is
> worse than saying nothing — it reads as done.

Bind the publication to loopback instead. In `docker-compose.hetzner.yml`, on
the `frontend` service:

```yaml
    ports:
      - "127.0.0.1:8080:3000"      # was "8080:3000"
```

Then `bash deploy/hetzner/update.sh`. Docker now listens only on the loopback
interface, so nothing external can reach it and no firewall rule is involved.
The SSH tunnel below still works, because it connects from *on* the host.

**Verify from another machine, not from the server** — checking locally
succeeds either way and proves nothing:

```bash
# from your laptop
curl --connect-timeout 5 -sS -o /dev/null http://<YOUR_HETZNER_IP>:8080 \
  && echo "STILL REACHABLE — not closed" \
  || echo "closed"
curl -sI https://trade.olbos.us | head -3     # still fine
```

This matters beyond tidiness. While `:8080` is open there is a plain-HTTP route
into the same app, and the Trade Desk's own 403 message tells an operator to go
enter the Operator API Key (`SECRET_KEY`) on the Risk Monitor page. Follow that
over `http://` and the key crosses the network in clear text. Closing the port
removes the unsafe path rather than relying on everyone remembering which URL
they are on.

For direct triage when the domain is down, tunnel — this works with the
loopback binding above and needs no change to expose anything:

```bash
ssh -L 8080:localhost:8080 root@<YOUR_HETZNER_IP>
```

### 8. Set up automated backups

`backup_db.sh` dumps the database daily but does nothing until its cron
entry is actually installed — run this once:
```bash
bash deploy/hetzner/install_backup_cron.sh
```
Configure an off-site target too (`BACKUP_RCLONE_REMOTE` or
`BACKUP_SCP_TARGET` in `backend/.env.prod`) — local-only backups don't
survive a disk failure.

---

## Updating after a code change

```bash
cd /opt/olbostrade
bash deploy/hetzner/update.sh
```

This pulls latest code, rebuilds, restarts, and runs any new migrations.

**Upgrading a stack created before `TRUSTED_PROXY_SECRET` existed:** add it to
`backend/.env.prod` before running `update.sh`, or Compose refuses to start and
the app goes down on what looks like a routine update:

```bash
echo "TRUSTED_PROXY_SECRET=$(openssl rand -hex 32)" >> backend/.env.prod
```

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

# Check database (role stays olbosquant deliberately — see Migration section)
docker exec -it olbostrade-db psql -U olbosquant -d olbostrade
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

## Migration

The production database was renamed live via `ALTER DATABASE olbosquantdb
RENAME TO olbostrade` (instant — no dump/restore needed, no data touched).

The Postgres **role** deliberately stays `olbosquant`. Renaming a role
requires connecting as a *different* superuser (Postgres refuses to let a
session rename its own login role), which means creating a temporary
superuser on production — real privilege escalation for a value that's
never visible outside this repo's own config (not in the UI, not in any
API response). Not worth it for a cosmetic-only rename. `docker-compose.hetzner.yml`
reflects this: `POSTGRES_USER`/`DATABASE_URL` use `olbosquant`, `POSTGRES_DB`
uses `olbostrade`.

If a fresh deployment ever needs the role renamed too (no existing data at
risk), it's the same trick as the database — just needs a second superuser
to issue the command:

```bash
docker exec -it olbostrade-db psql -U olbosquant -d postgres \
  -c "CREATE ROLE rename_helper WITH LOGIN SUPERUSER PASSWORD 'temp';"
docker exec -it olbostrade-db psql -U olbosquant -d postgres \
  -c "ALTER ROLE olbosquant RENAME TO olbostrade;"
docker exec -it olbostrade-db psql -U olbostrade -d postgres \
  -c "DROP ROLE rename_helper;"
```
Then update `DATABASE_URL`/`POSTGRES_USER`/the healthcheck in
`docker-compose.hetzner.yml` to `olbostrade` and redeploy.

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
