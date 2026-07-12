#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# OlbosTrade — reset trading / execution history (Hetzner)
#
# Clears all recorded live trades, journal entries, DB positions, and guardrail /
# EmotionGuard risk state so win rate, drawdown and P&L start from a clean slate.
#
# Usage (on the server, from the repo root /opt/olbostrade):
#   bash deploy/hetzner/reset_trading_history.sh          # prompts for confirmation
#   bash deploy/hetzner/reset_trading_history.sh --yes    # no prompt (scripted)
#
# Safe to run while the stack is up. It only clears OlbosTrade's database — it does
# NOT touch your real IBKR positions. Close any open positions in IB Gateway first
# if you want the broker flat too.
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# DB_USER/DB_NAME deliberately unchanged — see docker-compose.hetzner.yml note.
DB_CONTAINER="olbostrade-db"
DB_USER="olbosquant"
DB_NAME="olbosquantdb"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SQL_FILE="${SCRIPT_DIR}/reset_trading_history.sql"

if ! docker ps --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
  echo "ERROR: database container '${DB_CONTAINER}' is not running." >&2
  exit 1
fi
if [[ ! -f "${SQL_FILE}" ]]; then
  echo "ERROR: ${SQL_FILE} not found." >&2
  exit 1
fi

psql() { docker exec -i "${DB_CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" "$@"; }

echo "Current trading history in ${DB_NAME}:"
psql -t -A -F': ' -c "
  SELECT 'trades',              COUNT(*) FROM trades
  UNION ALL SELECT 'journal_entries',     COUNT(*) FROM journal_entries
  UNION ALL SELECT 'positions',           COUNT(*) FROM positions
  UNION ALL SELECT 'portfolio_snapshots', COUNT(*) FROM portfolio_snapshots
  UNION ALL SELECT 'guardrail_events',    COUNT(*) FROM guardrail_events;"
echo

if [[ "${1:-}" != "--yes" ]]; then
  read -r -p "This permanently deletes the above. Type YES to proceed: " confirm
  if [[ "${confirm}" != "YES" ]]; then
    echo "Aborted — nothing was deleted."
    exit 0
  fi
fi

echo "Resetting..."
psql -v ON_ERROR_STOP=1 < "${SQL_FILE}"
echo
echo "Done. Trading history cleared."
echo "Tip: restart the backend so any in-memory execution log resets too:"
echo "  docker restart olbostrade-backend"
