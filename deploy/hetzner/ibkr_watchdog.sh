#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# OlbosTrade — IB Gateway watchdog
#
# The gnzsnz/ib-gateway container can stay "Up" while the IB Gateway app inside it
# stops serving its API port (the classic IBKR daily-restart hang). When that
# happens the backend logs endless "TimeoutError / Failed to connect to IBKR".
#
# This script does a REAL API liveness probe (an ib_insync handshake from inside
# the backend container, which already has ib_insync) and restarts the gateway
# container only when the API is actually dead — with a cooldown so it doesn't
# restart again during the ~90s it takes the gateway to log back in.
#
# Intended to run from cron every few minutes (see install_ibkr_watchdog.sh).
# ═══════════════════════════════════════════════════════════════════════════════
set -uo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

VERBOSE=0
[ "${1:-}" = "--verbose" ] && VERBOSE=1

GATEWAY="ibkr-gateway"
BACKEND="olbostrade-backend"
GW_HOST="ibkr-gateway"          # docker service name the backend connects to
GW_PORT="4004"
PROBE_CLIENT_ID="99"            # distinct from the app's clientId to avoid clashes
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

# 2. Need the backend (has ib_insync) to run the probe; if it's down, skip.
if ! _running "$BACKEND"; then
  echo "$(ts) watchdog: $BACKEND not running — skipping probe"
  exit 0
fi

# 3. Real API liveness probe — an actual IBKR handshake.
probe=$(docker exec -i "$BACKEND" python3 - <<PY 2>/dev/null
import asyncio
async def main():
    try:
        from ib_insync import IB
        ib = IB()
        await ib.connectAsync("$GW_HOST", $GW_PORT, clientId=$PROBE_CLIENT_ID, timeout=8)
        ok = ib.isConnected()
        ib.disconnect()
        return ok
    except Exception:
        return False
print("OK" if asyncio.run(main()) else "DEAD")
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
