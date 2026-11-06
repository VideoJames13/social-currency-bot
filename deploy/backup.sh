#!/usr/bin/env bash
# Safe online backup of the database (works while the bot is running), verified,
# compressed, keeping the newest $KEEP. Run by bucks-bot-backup.timer nightly, or by
# hand:  sudo -u bucks bash deploy/backup.sh
set -euo pipefail
APP_DIR="${APP_DIR:-/home/bucks/social-currency-bot}"
BACKUP_DIR="${BACKUP_DIR:-/home/bucks/backups}"
KEEP="${KEEP:-14}"
DB="$APP_DIR/bucks.db"

if [[ ! -f "$DB" ]]; then
  echo "No database at $DB yet; nothing to back up."
  exit 0
fi
mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y-%m-%d_%H%M)"
tmp="$BACKUP_DIR/.bucks-$stamp.db.partial"
final="$BACKUP_DIR/bucks-$stamp.db.gz"
trap 'rm -f "$tmp" "$tmp.gz"' EXIT

# SQLite's backup API takes a consistent snapshot even mid-write.
sqlite3 "$DB" ".backup '$tmp'"
check="$(sqlite3 "$tmp" 'PRAGMA integrity_check;')"
if [[ "$check" != "ok" ]]; then
  echo "Backup FAILED integrity check: $check" >&2
  exit 1
fi
gzip -c "$tmp" > "$tmp.gz"
mv "$tmp.gz" "$final"   # only a complete, verified file ever gets the real name

# Keep the newest $KEEP backups.
ls -1t "$BACKUP_DIR"/bucks-*.db.gz | tail -n +"$((KEEP + 1))" | xargs -r rm -f
echo "Backed up to $final ($(du -h "$final" | cut -f1)); $(ls -1 "$BACKUP_DIR"/bucks-*.db.gz | wc -l) kept."
