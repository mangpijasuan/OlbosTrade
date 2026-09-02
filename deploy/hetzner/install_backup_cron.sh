#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Install the daily database backup as a cron job (06:10 UTC).
#
# backup_db.sh has always documented this cron line in a comment for a human
# to paste in manually — nothing ever installed it programmatically, so on a
# fresh deploy no backups actually run until someone does this by hand. This
# script closes that gap the same way install_ibkr_watchdog.sh already does
# for the IB Gateway watchdog.
#
# Run once on the server:
#   bash deploy/hetzner/install_backup_cron.sh
#
# Idempotent — re-running just refreshes the entry. Remove with:
#   crontab -l | grep -v backup_db.sh | crontab -
# ═══════════════════════════════════════════════════════════════════════════════
# Note: intentionally NOT using `set -e` — an empty crontab makes `grep` exit 1,
# which would abort the script before installing anything. Errors handled inline.
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WD="$DIR/backup_db.sh"
LOG="/var/log/olbostrade-backup.log"
CRON_LINE="10 6 * * * /usr/bin/bash $WD >> $LOG 2>&1"

if [ ! -f "$WD" ]; then
  echo "ERROR: $WD not found (did you git pull?)." >&2
  exit 1
fi
chmod +x "$WD"

if ! command -v crontab >/dev/null 2>&1; then
  echo "ERROR: crontab not installed. Install cron with:  apt-get install -y cron" >&2
  echo "       then re-run this script. (Or ask for a systemd-timer version.)" >&2
  exit 1
fi

# Build the new crontab: keep existing lines except any prior backup entry,
# drop blank lines, then append our line. `|| true` so an empty crontab is fine.
current="$(crontab -l 2>/dev/null || true)"
kept="$(printf '%s\n' "$current" | grep -v 'backup_db.sh' | sed '/^[[:space:]]*$/d' || true)"
{ [ -n "$kept" ] && printf '%s\n' "$kept"; echo "$CRON_LINE"; } | crontab -
if [ $? -ne 0 ]; then
  echo "ERROR: failed to write crontab." >&2
  exit 1
fi

echo "Installed daily DB backup — runs 06:10 UTC, logs to $LOG"
echo "Active entry:"
crontab -l | grep 'backup_db.sh' || echo "  (warning: entry not found after install)"

# Make sure the cron daemon is actually running, or the job never fires.
if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet cron 2>/dev/null || systemctl is-active --quiet crond 2>/dev/null; then
    echo "cron daemon: active"
  else
    echo "cron daemon not active — attempting to start it..."
    systemctl enable --now cron 2>/dev/null \
      || systemctl enable --now crond 2>/dev/null \
      || echo "  Could not auto-start cron. Check:  systemctl status cron"
  fi
fi

echo ""
echo "No off-site target configured yet? Set BACKUP_RCLONE_REMOTE or"
echo "BACKUP_SCP_TARGET in backend/.env.prod — local-only backups don't"
echo "survive a disk failure."
echo ""
echo "Test it now:"
echo "  bash $WD"
