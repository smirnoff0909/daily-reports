#!/usr/bin/env bash
# Ежедневный дамп базы. В cron: 0 2 * * * /opt/daily-reports/scripts/backup.sh
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/daily-reports}"
KEEP_DAYS="${KEEP_DAYS:-30}"
STAMP="$(date +%Y-%m-%d)"

mkdir -p "$BACKUP_DIR"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-reports}" "${POSTGRES_DB:-reports}" \
  | gzip > "$BACKUP_DIR/reports-$STAMP.sql.gz"

find "$BACKUP_DIR" -name 'reports-*.sql.gz' -mtime "+$KEEP_DAYS" -delete
echo "Готово: $BACKUP_DIR/reports-$STAMP.sql.gz"
