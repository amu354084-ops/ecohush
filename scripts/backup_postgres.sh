#!/usr/bin/env sh
set -eu

: "${POSTGRES_HOST:=db}"
: "${POSTGRES_PORT:=5432}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${BACKUP_DIR:=/var/backups/erp}"
: "${BACKUP_RETENTION_DAYS:=7}"

mkdir -p "$BACKUP_DIR"
timestamp=$(date -u +%Y%m%d_%H%M%S)
backup_file="$BACKUP_DIR/postgres_${POSTGRES_DB}_${timestamp}.sql.gz"

PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
  --host="$POSTGRES_HOST" \
  --port="$POSTGRES_PORT" \
  --username="$POSTGRES_USER" \
  --dbname="$POSTGRES_DB" \
  --no-owner --no-privileges | gzip -9 > "$backup_file"

find "$BACKUP_DIR" -type f -name 'postgres_*.sql.gz' -mtime "+$BACKUP_RETENTION_DAYS" -delete
printf '%s\n' "$backup_file"

if [ -n "${TIMEWEB_S3_BUCKET:-}" ] && [ "${TIMEWEB_S3_BUCKET}" != "CHANGE_ME" ] && command -v aws >/dev/null 2>&1; then
  AWS_ACCESS_KEY_ID="${TIMEWEB_S3_ACCESS_KEY:-}" \
  AWS_SECRET_ACCESS_KEY="${TIMEWEB_S3_SECRET_KEY:-}" \
  AWS_DEFAULT_REGION="${TIMEWEB_S3_REGION:-ru-1}" \
  aws s3 cp "$backup_file" "s3://${TIMEWEB_S3_BUCKET}/postgres/" \
    --endpoint-url "${TIMEWEB_S3_ENDPOINT:-https://s3.timeweb.cloud}"
fi
