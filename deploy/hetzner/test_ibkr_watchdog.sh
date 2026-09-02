#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Tests for ibkr_watchdog.sh's restart decision logic.
#
# Exists because a bad predicate in this script caused a production incident on
# 2026-08-27: it restarted the IB Gateway every 15 minutes indefinitely (9 times
# between 02:20 and 07:00), which blacked out account data and left margin
# guardrails blind while autopilot was on. The decisions this script makes are
# unattended and destructive, so they get tested.
#
# The probe's verdict is computed by Python embedded in the script, so these
# tests run that Python for real against a local HTTP server serving canned
# /api/health/detail payloads. An earlier draft stubbed `docker exec` to echo a
# fixed verdict — which meant the predicate was never exercised and the suite
# passed against the known-buggy version. Verified: reintroducing the old
# `connected and queue_depth < 30` predicate makes this suite fail.
#
# Nothing real is touched: docker is a shell function, the "backend" is a
# temp-dir file server, and no IBKR connection is made.
#
#   bash deploy/hetzner/test_ibkr_watchdog.sh
# ═══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${WATCHDOG_SCRIPT:-$HERE/ibkr_watchdog.sh}"
PASS=0; FAIL=0

TMP="$(mktemp -d)"
SRV_PID=""
cleanup() {
  if [ -n "$SRV_PID" ]; then
    kill "$SRV_PID" 2>/dev/null
    wait "$SRV_PID" 2>/dev/null   # reap quietly; avoids a "Terminated" line
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

# ── Fake backend serving /api/health/detail ───────────────────────────────────
mkdir -p "$TMP/srv/api/health"
HEALTH_FILE="$TMP/srv/api/health/detail"
echo '{}' > "$HEALTH_FILE"

# Pick a free port so this never collides with a real dev server.
PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$TMP/srv" >/dev/null 2>&1 &
SRV_PID=$!
for _ in $(seq 1 50); do
  python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1',$PORT))==0 else 1)" 2>/dev/null && break
  sleep 0.1
done
export PORT

set_health() {   # connected(true|false) p0_depth
  cat > "$HEALTH_FILE" <<JSON
{"ibkr": {"connected": $1, "coordinator": {"queue_depth": {"P0": $2, "P1": 0, "P2": 0}}}}
JSON
}

# ── Stub docker ───────────────────────────────────────────────────────────────
# An exported *function*, not a stub binary on PATH: ibkr_watchdog.sh prepends
# the system directories to PATH, which would shadow a stub binary with the real
# docker. Bash resolves functions before PATH, so this cannot be bypassed.
#
# `exec` runs the script's real embedded Python, repointing it at our fake
# server — that is what gives the predicate tests their teeth.
docker() {
  case "$1" in
    inspect) echo "true" ;;
    exec)    sed "s|127\.0\.0\.1:8000|127.0.0.1:${PORT}|" | python3 - ;;
    restart|start) echo "$*" >> "${RESTART_LOG:?}" ;;
  esac
  return 0
}
export -f docker

# ── Harness ───────────────────────────────────────────────────────────────────
run_case() {   # connected p0_depth [stamp_age_seconds] [history epochs]
  set_health "$1" "$2"
  local stamp_age="${3:-}" history="${4:-}"
  rm -f /tmp/ibkr-watchdog-last-restart /tmp/ibkr-watchdog-restart-history
  [ -n "$stamp_age" ] && echo $(( $(date +%s) - stamp_age )) > /tmp/ibkr-watchdog-last-restart
  [ -n "$history" ] && printf '%s\n' $history > /tmp/ibkr-watchdog-restart-history
  export RESTART_LOG="$TMP/restarts.log"; : > "$RESTART_LOG"
  OUTPUT="$(bash "$SCRIPT" 2>&1)"
  RESTARTS="$(wc -l < "$RESTART_LOG" | tr -d ' ')"
}

ok()  { PASS=$((PASS+1)); echo "  PASS  $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL  $1"; echo "        output: $OUTPUT"; }
assert_restarts() { [ "$RESTARTS" = "$1" ] && ok "$2" || bad "$2 (expected $1 restart(s), got $RESTARTS)"; }
assert_contains() { case "$OUTPUT" in *"$1"*) ok "$2" ;; *) bad "$2 (missing: $1)" ;; esac; }

echo "ibkr_watchdog.sh decision logic"

# ── The regression that caused the incident ───────────────────────────────────
# Connected, but an enormous P0 backlog. The old predicate called this DEAD and
# restarted; a gateway restart cannot drain an app-side queue, so it looped
# forever. Connection is up → nothing for a gateway restart to fix.
run_case true 429
assert_restarts 0 "deep P0 queue while connected does NOT trigger a restart"

run_case true 4000
assert_restarts 0 "even an extreme P0 backlog does not trigger a restart"

run_case true 5
assert_restarts 0 "healthy probe does not restart"

# ── Genuine hang: the one thing a gateway restart can fix ─────────────────────
run_case false 0
assert_restarts 1 "disconnected socket triggers a restart"

run_case false 500
assert_restarts 1 "disconnected socket restarts regardless of queue depth"

# ── Cooldown ──────────────────────────────────────────────────────────────────
run_case false 0 60
assert_restarts 0 "no restart inside the cooldown window"
assert_contains "within cooldown" "cooldown is reported"

# ── Circuit breaker ───────────────────────────────────────────────────────────
NOW=$(date +%s)
run_case false 0 2000 "$((NOW-100)) $((NOW-200)) $((NOW-300)) $((NOW-400))"
assert_restarts 0 "breaker blocks a 5th restart inside the window"
assert_contains "CIRCUIT BREAKER OPEN" "breaker escalates loudly"

run_case false 0 2000 "$((NOW-100)) $((NOW-200)) $((NOW-300))"
assert_restarts 1 "breaker still permits restarts under budget"

OLD=$((NOW - 30000))   # ~8.3h ago, outside the 6h window
run_case false 0 2000 "$OLD $((OLD+1)) $((OLD+2)) $((OLD+3))"
assert_restarts 1 "restarts older than the window do not count toward the breaker"

run_case true 5 "" "$((NOW-100)) $((NOW-200)) $((NOW-300)) $((NOW-400))"
[ ! -s /tmp/ibkr-watchdog-restart-history ] \
  && ok "healthy probe clears restart history" \
  || bad "healthy probe clears restart history"

# ── Backend unreachable ───────────────────────────────────────────────────────
# If the probe itself cannot run, that is not evidence the gateway is hung.
# It still reads DEAD (fail-safe), but the cooldown/breaker bound the damage.
# Note this deliberately does NOT go through run_case: that helper rewrites the
# health file, which would undo the very condition being tested.
mv "$HEALTH_FILE" "$HEALTH_FILE.hidden"
rm -f /tmp/ibkr-watchdog-last-restart /tmp/ibkr-watchdog-restart-history
export RESTART_LOG="$TMP/restarts.log"; : > "$RESTART_LOG"
OUTPUT="$(bash "$SCRIPT" 2>&1)"
RESTARTS="$(wc -l < "$RESTART_LOG" | tr -d ' ')"
mv "$HEALTH_FILE.hidden" "$HEALTH_FILE"
assert_restarts 1 "unreadable health endpoint is treated as DEAD"

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ]
