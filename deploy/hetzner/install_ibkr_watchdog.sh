#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Install the IB Gateway watchdog as a cron job (every 5 minutes).
#
# Run once on the server:
#   bash deploy/hetzner/install_ibkr_watchdog.sh
#
# Idempotent — re-running just refreshes the entry. Remove with:
#   crontab -l | grep -v ibkr_watchdog.sh | crontab -
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WD="$DIR/ibkr_watchdog.sh"
LOG="/var/log/ibkr-watchdog.log"
CRON_LINE="*/5 * * * * $WD >> $LOG 2>&1"

if [ ! -f "$WD" ]; then
  echo "ERROR: $WD not found (did you git pull?)." >&2
  exit 1
fi
chmod +x "$WD"

if ! command -v crontab >/dev/null 2>&1; then
  echo "ERROR: crontab not available. Install cron (apt-get install -y cron) or" >&2
  echo "       ask for a systemd-timer version instead." >&2
  exit 1
fi

# Replace any prior entry, then add the current one.
( crontab -l 2>/dev/null | grep -v 'ibkr_watchdog.sh' ; echo "$CRON_LINE" ) | crontab -

echo "✅ Installed IBKR watchdog — runs every 5 min, logs to $LOG"
echo ""
echo "Active crontab entry:"
crontab -l | grep 'ibkr_watchdog.sh' || true
echo ""
echo "Test it once now:"
echo "  bash $WD && tail -n 5 $LOG 2>/dev/null"
