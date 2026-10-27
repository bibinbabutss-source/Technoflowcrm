#!/usr/bin/env bash
# Back up the PostgreSQL database and the uploaded documents.
# Usage: bash deploy/backup.sh            (reads DATABASE_URL and MEDIA_ROOT from the environment / .env)
# Keeps the last $KEEP_DAYS days (default 30) in $BACKUP_DIR (default /var/backups/technoflow_crm).
# Copy the backup folder to another machine or cloud storage regularly - a backup on the same disk
# does not protect against a disk failure.
set -o errexit -o nounset -o pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/technoflow_crm}"
KEEP_DAYS="${KEEP_DAYS:-30}"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
umask 077   # backups contain customer data: owner-only permissions

echo "Database -> $BACKUP_DIR/db-$STAMP.dump"
pg_dump --format=custom --no-owner --dbname="$DATABASE_URL" --file="$BACKUP_DIR/db-$STAMP.dump"

if [ -d "${MEDIA_ROOT:-}" ]; then
  echo "Documents -> $BACKUP_DIR/media-$STAMP.tar.gz"
  tar -czf "$BACKUP_DIR/media-$STAMP.tar.gz" -C "$MEDIA_ROOT" .
fi

# Quick integrity check of the dump
pg_restore --list "$BACKUP_DIR/db-$STAMP.dump" > /dev/null

find "$BACKUP_DIR" -name 'db-*.dump' -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name 'media-*.tar.gz' -mtime +"$KEEP_DAYS" -delete
echo "Backup finished: $STAMP"
