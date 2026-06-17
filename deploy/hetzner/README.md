# Hetzner + GitHub deployment

This deployment path runs OlbosQuant on a Hetzner Ubuntu server and deploys from
GitHub Actions. Your MacBook is not part of the runtime.

## What runs on the server

- `ib-gateway` — Interactive Brokers Gateway container, paper port `4002`
- `backend` — FastAPI app built by GitHub Actions
- `frontend` — Vite/nginx app built by GitHub Actions
- `postgres` and `redis`
- `nginx` and `certbot`

The backend still uses the IBKR socket API through `ib_insync`, because that is
the broker implementation already used by the app. This removes the Mac
dependency by running IB Gateway on the Hetzner server.

## About IBKR Client Portal

IBKR Client Portal Gateway is a different HTTPS/Web API product from IB Gateway.
It is not currently implemented by the backend broker interface.

Client Portal also has important operational limits:

- login must be completed through a browser flow;
- 2FA is mandatory;
- sessions expire daily and can time out without keep-alives;
- IBKR does not officially provide a fully unattended individual-user login flow;
- one IBKR username can only have one active brokerage session across Client
  Portal, TWS, Gateway, mobile, etc.

For a reliable first remote deployment, use the included `ib-gateway` container.
If you still want a native Client Portal REST broker later, add it as a separate
broker implementation (`BROKER=ibkr_client_portal`) after the server deployment
is stable.

## 1. Provision the Hetzner server

Create an Ubuntu 22.04 or 24.04 server in Hetzner, point your DNS `A` record at
it, then run as root:

```bash
bash deploy/hetzner/provision.sh
```

Or copy the script contents to the server and run it there. It installs Docker,
creates a `deploy` user, opens ports `22`, `80`, and `443`, and creates
`/opt/olbosquant`.

## 2. Create `/opt/olbosquant/.env.hetzner`

On the server:

```bash
sudo -iu deploy
cd /opt/olbosquant
cp deploy/hetzner/env.hetzner.example .env.hetzner
nano .env.hetzner
```

Minimum values to fill:

- `DOMAIN`
- `CERTBOT_EMAIL`
- `GHCR_IMAGE_PREFIX` (`ghcr.io/<owner>/<repo>`, lowercase)
- `IBKR_USERNAME`
- `IBKR_PASSWORD`
- `VNC_PASSWORD`
- `POSTGRES_PASSWORD`
- `SECRET_KEY`
- `KILL_SWITCH_RESET_CODE`

Generate secrets with:

```bash
openssl rand -hex 32
```

If the GitHub repo/packages are private, either set `GHCR_USERNAME` and
`GHCR_TOKEN` in `.env.hetzner`, or let the GitHub workflow pass a token during
deployment.

## 3. Configure GitHub secrets

In GitHub repository settings, add:

| Secret | Value |
| --- | --- |
| `HETZNER_HOST` | Server IP or hostname |
| `HETZNER_USER` | Usually `deploy` |
| `HETZNER_SSH_KEY` | Private key that can SSH to the deploy user |
| `HETZNER_APP_DIR` | Optional, defaults to `/opt/olbosquant` |
| `VITE_ADMIN_API_KEY` | Optional; same value as `SECRET_KEY` if UI admin buttons should work |

Then run **Actions → Deploy to Hetzner → Run workflow**.

The workflow:

1. builds backend and frontend images from GitHub;
2. pushes them to GHCR;
3. copies compose/deploy files to Hetzner;
4. runs `deploy/hetzner/deploy.sh` over SSH.

## 4. Complete IBKR Gateway login on the server

IBKR still requires login/2FA. The difference is that you do it on the server,
not on your Mac as a process dependency.

Create an SSH tunnel:

```bash
ssh -L 5900:127.0.0.1:5900 deploy@YOUR_SERVER_IP
```

Open a VNC client to:

```text
127.0.0.1:5900
```

Use `VNC_PASSWORD`, log in to IB Gateway, and complete IBKR 2FA. The container
will keep running on Hetzner after your Mac is closed.

Check the stack:

```bash
cd /opt/olbosquant
docker compose --env-file .env.hetzner -f docker-compose.hetzner.yml ps
docker compose --env-file .env.hetzner -f docker-compose.hetzner.yml logs -f backend ib-gateway
```

## 5. Safety checklist before live trading

- Start with `IBKR_TRADING_MODE=paper` and `IBKR_PORT=4002`.
- Keep `OPTIONS_FLOW_ENABLED=false` unless OPRA/live data is configured.
- Confirm `/api/market/broker` reports `connected`.
- Confirm kill switch works in paper mode.
- Do not set `IBKR_PORT=4001` or use live credentials until paper mode has been
  verified end-to-end on the server.
