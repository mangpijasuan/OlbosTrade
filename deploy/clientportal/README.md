# IBKR Client Portal Web API gateway (`clientportal.gw`)

Headless deployment of IBKR's **Client Portal Web API** gateway (REST/WebSocket
on port 5000), used by OlbosQuant when `BROKER=ibkr_cp`.

This is a **different API** from the `ib_insync` TWS socket connection
(`BROKER=ibkr`). It is added **alongside** ib_insync, not as a replacement.

> **Scope today:** the `ClientPortalClient` is **read-only** (accounts,
> positions, quotes, bars, greeks, best-effort chain) plus session keepalive.
> Order execution is intentionally **disabled** (raises `NotImplementedError`)
> until verified against a live authenticated gateway. For live order execution
> keep `BROKER=ibkr` (ib_insync).

## Why this exists
The gateway runs on the **always-on droplet**, so your laptop never has to be
on. You authenticate from **any** browser (laptop or phone) via an SSH tunnel.

### Honest caveats
- **Not zero-touch.** The gateway needs a **one-time browser login** and the
  brokerage session **times out (~daily)**. There is **no IBC-style auto-relogin**
  for Client Portal — you re-authenticate from a browser when the session drops.
  The client keeps the session warm with `/tickle` but cannot log in for you.
- **Egress:** the gateway must reach `https://api.ibkr.com`. Ensure the droplet's
  network policy allows it.
- **2FA:** live logins prompt IBKR Mobile 2FA. Paper accounts do not.

## Run it

### Docker (recommended — wired into compose)
```bash
# dev
docker compose up -d ib-gateway-cp
# prod
docker compose -f docker-compose.prod.yml up -d ib-gateway-cp
```
The service binds **`127.0.0.1:5000` only** — the auth gateway is never exposed
publicly.

### Authenticate (one-time per session)
From your local machine, tunnel to the droplet and open the login page:
```bash
ssh -N -L 5000:127.0.0.1:5000 user@your-droplet
# then in a browser:
open https://localhost:5000        # accept the self-signed cert, then log in
```
After "Client login succeeds" you can close the browser. Verify:
```bash
curl -sk https://localhost:5000/v1/api/iserver/auth/status
```

## Point the backend at it
In `.env` / `.env.prod`:
```bash
BROKER=ibkr_cp
CP_GATEWAY_URL=https://ib-gateway-cp:5000   # compose service name
CP_GATEWAY_VERIFY_SSL=false                 # gateway ships a self-signed cert
# CP_ACCOUNT_ID=                            # optional; auto-detected if blank
# CP_TICKLE_INTERVAL_S=60                   # session keepalive cadence
```
(When running the backend outside Docker against a local gateway, use
`CP_GATEWAY_URL=https://127.0.0.1:5000`.)

## Notes
- The gateway is **vendored** here (exact uploaded version) for reproducible
  builds; `.gitignore` is overridden to keep its `dist/` and `build/` jars.
- Config: `root/conf.yaml` (port, SSL, IP allowlist). The allowlist includes
  Docker network ranges (`172.*`, `10.*`) so the backend container can reach it.
- API reference: https://interactivebrokers.github.io/cpwebapi
