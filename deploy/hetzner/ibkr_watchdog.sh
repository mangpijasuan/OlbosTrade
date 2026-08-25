#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# OlbosTrade — IB Gateway watchdog
#
# The gnzsnz/ib-gateway container can stay "Up" while the IB Gateway app inside it
# stops serving its API port (the classic IBKR daily-restart hang). When that
# happens the backend logs endless "TimeoutError / Failed to connect to IBKR".
#
# This script checks liveness by reading the backend's own /api/health/detail
# (already-running FastAPI process, no new socket to the gateway) and restarts
# the gateway container only when that snapshot looks dead — with a cooldown so
# it doesn't restart again during the ~90s it takes the gateway to log back in.
#
# PRIOR VERSION BUG (found 2026-08-25): this used to open a second, independent
# ib_insync connection (clientId=99) as its liveness probe. Correlating gateway
# logs against this cron's own schedule proved that connection was the direct
# cause of "remove Client 2" disconnects on the app's real session — IB Gateway
# kicked the existing clientId=2 session every single time this probe connected
# (~286-288 collisions/day while the cron ran, essentially zero when it didn't;
# see the plan doc's "Out-of-band incident" section for the full log analysis).
# The fix opening a second connection was supposed to catch was real, but the
# probe's own side effect was worse than the daily hang it existed to catch —
# so this version checks the app's already-open connection's self-reported
# state instead of ever dialing a second one.
#
# Intended to run from cron every few minutes (see install_ibkr_watchdog.sh).
# ═══════════════════════════════════════════════════════════════════════════════
set -uo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

VERBOSE=0
[ "${1:-}" = "--verbose" ] && VERBOSE=1

GATEWAY="ibkr-gateway"
BACKEND="olbostrade-backend"
# P0 queue depth above this, alongside a disconnected/degraded reading, is
# treated as "stuck" rather than ordinary transient churn (normal operation
# sits in the low single digits to low tens; the real incident this was
# tuned against reached the hundreds/thousands).
QUEUE_DEPTH_THRESHOLD=30
COOLDOWN=900                    # seconds; don't restart again within 15 min
STAMP="/tmp/ibkr-watchdog-last-restart"

ts() { date -u +%FT%TZ; }
vsay() { [ "$VERBOSE" = 1 ] && echo "$(ts) $*"; return 0; }

_running() { [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || echo false)" = "true" ]; }

mark_restart() { date +%s > "$STAMP"; }

in_cooldown() {
  [ -f "$STAMP" ] || return 1
  local last now; last=$(cat "$STAMP" 2>/dev/null || echo 0); now=$(date +%s)
  [ $((now - last)) -lt "$COOLDOWN" ]
}

# 1. Gateway container missing or stopped → just (re)start it.
if ! _running "$GATEWAY"; then
  if in_cooldown; then
    echo "$(ts) watchdog: $GATEWAY not running but within cooldown — waiting"
    exit 0
  fi
  echo "$(ts) watchdog: $GATEWAY not running — starting it"
  docker start "$GATEWAY" >/dev/null 2>&1 || docker restart "$GATEWAY" >/dev/null 2>&1 || true
  mark_restart
  exit 0
fi

# 2. Need the backend running to read its own /api/health/detail; if it's
#    down, skip (a dead backend isn't this watchdog's problem to fix).
if ! _running "$BACKEND"; then
  echo "$(ts) watchdog: $BACKEND not running — skipping probe"
  exit 0
fi

# 3. Liveness check via the backend's own already-open connection — reads
#    /api/health/detail from inside the backend container (no new socket to
#    the gateway, so this can never itself disturb the app's live session).
#    "DEAD" means either the app's socket reports disconnected, or the P0
#    queue is stuck deep enough that the connection is unresponsive in
#    practice even if isConnected() hasn't noticed yet.
probe=$(docker exec -i "$BACKEND" python3 - <<PY 2>/dev/null
import json, urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:8000/api/health/detail", timeout=8) as r:
        data = json.load(r)
    ibkr = data.get("ibkr", {}) or {}
    connected = bool(ibkr.get("connected"))
    queue_depth = float((ibkr.get("coordinator", {}) or {}).get("queue_depth", {}).get("P0", 0) or 0)
    ok = connected and queue_depth < $QUEUE_DEPTH_THRESHOLD
except Exception:
    ok = False
print("OK" if ok else "DEAD")
PY
)
probe=$(printf '%s' "$probe" | tr -d '[:space:]')

if [ "$probe" = "OK" ]; then
  vsay "watchdog: gateway healthy (IBKR API probe=OK)"
  exit 0   # healthy — nothing to do
fi

# 4. Probe failed → restart the gateway, respecting the cooldown.
if in_cooldown; then
  echo "$(ts) watchdog: probe=${probe:-empty} but within cooldown — gateway likely still logging in"
  exit 0
fi
echo "$(ts) watchdog: IBKR API probe=${probe:-empty} — restarting $GATEWAY"
docker restart "$GATEWAY" >/dev/null 2>&1 || true
mark_restart
