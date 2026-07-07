#!/usr/bin/env bash
# Family Portal — consistent SQLite database backup + retention.
#
# Runs daily from systemd (family-portal-backup.service/.timer), or by hand:
#   bash deploy/backup-db.sh
#
# Uses the SQLite *online backup* API (via the app's venv python) so the copy
# is transactionally consistent even while the app is writing to the DB —
# NEVER a raw `cp`, which can capture a torn/half-written file.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/family-portal}"
PYTHON="${PYTHON:-$APP_DIR/venv/bin/python}"
# Resolve the live DB path exactly like server/database.py does:
#   $FAMILY_PORTAL_DB if set, else <app>/data/family.db
DB_PATH="${FAMILY_PORTAL_DB:-$APP_DIR/data/family.db}"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
KEEP="${KEEP:-14}"

log() { echo "[backup-db] $*"; }

if [[ ! -f "$DB_PATH" ]]; then
  log "ERROR: database not found at '$DB_PATH' (set FAMILY_PORTAL_DB to override)"
  exit 1
fi

# Prefer the app venv's python; fall back to any python3 on PATH.
if [[ ! -x "$PYTHON" ]]; then
  log "venv python not found at '$PYTHON' — falling back to system python3"
  PYTHON="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON" ]]; then
  log "ERROR: no python interpreter available for the backup"
  exit 1
fi

mkdir -p "$BACKUP_DIR"

STAMP="$(date +%Y%m%d-%H%M)"
DEST="$BACKUP_DIR/family-${STAMP}.db"

log "backing up '$DB_PATH' -> '$DEST'"

# Online backup: stream pages from the live DB into a fresh file via the
# sqlite3 backup() API. Safe under concurrent readers/writers.
"$PYTHON" - "$DB_PATH" "$DEST" <<'PY'
import sqlite3
import sys

src_path, dest_path = sys.argv[1], sys.argv[2]
src = sqlite3.connect(src_path)
try:
    dest = sqlite3.connect(dest_path)
    try:
        with dest:
            src.backup(dest)
    finally:
        dest.close()
finally:
    src.close()
PY

SIZE="$(du -h "$DEST" 2>/dev/null | cut -f1 || echo '?')"
log "wrote '$DEST' (${SIZE})"

# Retention: keep only the newest $KEEP backups; prune the rest (oldest first).
mapfile -t OLD < <(ls -1t "$BACKUP_DIR"/family-*.db 2>/dev/null | tail -n +"$((KEEP + 1))")
if (( ${#OLD[@]} > 0 )); then
  log "pruning ${#OLD[@]} old backup(s), keeping newest ${KEEP}"
  for f in "${OLD[@]}"; do
    rm -f -- "$f" && log "  removed $(basename "$f")"
  done
else
  log "no pruning needed (<= ${KEEP} backups on disk)"
fi

log "done"
