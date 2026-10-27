#!/usr/bin/env bash
# Restore a backup made by backup.sh. THIS REPLACES THE CURRENT DATABASE CONTENTS.
# Usage: bash deploy/restore.sh /var/backups/technoflow_crm/db-YYYYMMDD-HHMMSS.dump [media-....tar.gz]
# Stop the web service first:  sudo systemctl stop technoflow-crm
set -o errexit -o nounset -o pipefail

DUMP="${1:?Give the .dump file to restore}"
MEDIA_ARCHIVE="${2:-}"

read -r -p "Replace ALL data in the CRM database with $DUMP? Type YES to continue: " answer
[ "$answer" = "YES" ] || { echo "Cancelled."; exit 1; }

pg_restore --clean --if-exists --no-owner --dbname="$DATABASE_URL" "$DUMP"

if [ -n "$MEDIA_ARCHIVE" ]; then
  mkdir -p "$MEDIA_ROOT"
  tar -xzf "$MEDIA_ARCHIVE" -C "$MEDIA_ROOT"
fi

python manage.py migrate --no-input   # in case the backup is older than the code
echo "Restore finished. Start the service again: sudo systemctl start technoflow-crm"
