#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/root/app"
REPO_URL="${REPO_URL:-https://github.com/amu354084-ops/ecohush.git}"
BRANCH="${BRANCH:-main}"
VPS_IPV6="${VPS_IPV6:-2a03:6f01:1:2::1:80c1}"
VPS_IPV4="${VPS_IPV4:-}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script as root in the Timeweb web console."
  exit 1
fi

read -r -p "GitHub repository URL (Enter for ecohush): " repo_input
REPO_URL="${repo_input:-$REPO_URL}"
read -r -p "Git branch [main]: " branch_input
BRANCH="${branch_input:-main}"
read -r -p "VPS public IPv4 (optional): " VPS_IPV4_INPUT
VPS_IPV4="${VPS_IPV4_INPUT:-$VPS_IPV4}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl git openssl

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is unavailable after Docker installation."
  exit 1
fi

if [[ -e "$APP_DIR" && ! -d "$APP_DIR/.git" ]]; then
  echo "$APP_DIR exists but is not a Git checkout; refusing to overwrite it."
  exit 1
fi
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch --depth 1 origin "$BRANCH"
  git -C "$APP_DIR" checkout -B "$BRANCH" "origin/$BRANCH"
else
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

if [[ ! -f docker-compose.prod.yml ]]; then
  echo "docker-compose.prod.yml was not found in the repository."
  exit 1
fi

umask 077
read -r -s -p "Initial admin password (not echoed): " ADMIN_PASSWORD
echo
read -r -s -p "Telegram bot token (blank to disable): " TELEGRAM_BOT_TOKEN
echo
read -r -p "Telegram chat ID (blank to disable): " TELEGRAM_CHAT_ID
read -r -p "Timeweb S3 bucket (blank to disable): " TIMEWEB_S3_BUCKET
if [[ -n "$TIMEWEB_S3_BUCKET" ]]; then
  read -r -p "Timeweb S3 access key: " TIMEWEB_S3_ACCESS_KEY
  read -r -s -p "Timeweb S3 secret key (not echoed): " TIMEWEB_S3_SECRET_KEY
  echo
else
  TIMEWEB_S3_ACCESS_KEY=""
  TIMEWEB_S3_SECRET_KEY=""
fi

POSTGRES_PASSWORD="$(openssl rand -hex 24)"
ERP_AUTH_SECRET="$(openssl rand -hex 48)"
cat > .env.production <<EOF
USE_SQLITE=0
POSTGRES_DB=erp_local
POSTGRES_USER=erp_user
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
DATABASE_URL=postgresql+asyncpg://erp_user:$POSTGRES_PASSWORD@db:5432/erp_local
ERP_AUTH_SECRET=$ERP_AUTH_SECRET
SECRET_KEY=$ERP_AUTH_SECRET
ERP_INITIAL_ADMIN_PASSWORD=$ADMIN_PASSWORD
ERP_HOST=0.0.0.0
ERP_SERVER_PORT=1833
ERP_CORS_ORIGINS=http://localhost:1833,http://127.0.0.1:1833${VPS_IPV4:+,http://$VPS_IPV4:1833}
BACKUP_DIR=/var/backups/erp
BACKUP_TIMEZONE=UTC
BACKUP_HOUR=23
BACKUP_MINUTE=00
LOG_LEVEL=INFO
LOG_FILE=/var/log/erp/erp.log
TIMEWEB_S3_ENDPOINT=https://s3.timeweb.cloud
TIMEWEB_S3_BUCKET=$TIMEWEB_S3_BUCKET
TIMEWEB_S3_REGION=ru-1
TIMEWEB_S3_ACCESS_KEY=$TIMEWEB_S3_ACCESS_KEY
TIMEWEB_S3_SECRET_KEY=$TIMEWEB_S3_SECRET_KEY
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID
EOF
chmod 600 .env.production

# Validate and start the production stack.
docker compose --env-file .env.production -f docker-compose.prod.yml config >/dev/null
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build

echo "Waiting for the application container..."
for attempt in {1..30}; do
  if curl -fsS http://127.0.0.1:1833/ready; then
    echo
    echo "ERP is ready on local port 1833."
    exit 0
  fi
  sleep 2
done

echo "The stack started but /ready did not become healthy. Logs:"
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 web db
exit 1
