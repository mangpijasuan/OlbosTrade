#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# OlbosQuant — Daily database backup (with optional off-site copy)
#
# Dumps the Postgres database from the olbosquant-db container, compresses and
# timestamps it, prunes old local dumps, and — if an off-site target is
# configured — copies the dump off the box.
#
# Run manually:        bash deploy/hetzner/backup_db.sh
# Run daily via cron:  see "Cron setup" at the bottom of this file.
#
# Off-site copy (optional) — set ONE of these in backend/.env.prod:
#   BACKUP_RCLONE_REMOTE="myremote:olbosquant-backups"   # rclone (S3/B2/GDrive/…)
#   BACKUP_SCP_TARGET="user@host:/path/olbosquant-backups" # scp over SSH
# Without either, backups are kept locally only (better than nothing, but a disk
# failure loses them — configure an off-site target before live capital).
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# Load config (DB password, optional off-site target)
if [[ -f backend/.env.prod ]]; then
  set -a; source backend/.env.prod; set +a
fi

DB_CONTAINER="${DB_CONTAINER:-olbosquant-db}"
DB_USER="${POSTGRES_USER:-olbosquant}"
DB_NAME="${POSTGRES_DB:-olbosquantdb}"
BACKUP_DIR="${BACKUP_DIR:-/opt/olbosquant-backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/olbosquant-${STAMP}.sql.gz"

echo "[1/4] Dumping $DB_NAME from $DB_CONTAINER..."
# pg_dump inside the container; gzip on the host. pipefail makes a dump failure
# fail the whole script (so cron/monitoring sees a non-zero exit).
docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$OUT"
SIZE="$(du -h "$OUT" | cut -f1)"
echo "      ✅ Wrote $OUT ($SIZE)"

echo "[2/4] Pruning local backups older than ${RETENTION_DAYS} days..."
find "$BACKUP_DIR" -name 'olbosquant-*.sql.gz' -type f -mtime "+${RETENTION_DAYS}" -delete
echo "      ✅ Pruned"

echo "[3/4] Off-site copy..."
if [[ -n "${BACKUP_RCLONE_REMOTE:-}" ]]; then
  rclone copy "$OUT" "$BACKUP_RCLONE_REMOTE" && echo "      ✅ rclone → $BACKUP_RCLONE_REMOTE"
elif [[ -n "${BACKUP_SCP_TARGET:-}" ]]; then
  scp -q "$OUT" "$BACKUP_SCP_TARGET" && echo "      ✅ scp → $BACKUP_SCP_TARGET"
else
  echo "      ⚠ No off-site target set (BACKUP_RCLONE_REMOTE / BACKUP_SCP_TARGET) — local only."
fi

echo "[4/4] Verifying dump integrity..."
gzip -t "$OUT" && echo "      ✅ gzip OK"

echo ""
echo "  ✅ Backup complete: $OUT"

# ───────────────────────────────────────────────────────────────────────────────
# Cron setup (run once on the server):
#   crontab -e
# then add — daily at 06:10 UTC, logging to a file:
#   10 6 * * * /usr/bin/bash /opt/olbosquant/deploy/hetzner/backup_db.sh >> /var/log/olbosquant-backup.log 2>&1
#
# Restore a dump into the running DB container:
#   gunzip -c /opt/olbosquant-backups/olbosquant-YYYYMMDD-HHMMSS.sql.gz \
#     | docker exec -i olbosquant-db psql -U olbosquant -d olbosquantdb
# ───────────────────────────────────────────────────────────────────────────────
