# Deployment: ERP Local

Этот документ описывает первый запуск на VPS после покупки Timeweb. Локальный SQLite-режим не изменяется.

## Требования

- Ubuntu/Debian VPS
- Docker Engine и Docker Compose plugin
- DNS-запись домена на IP VPS
- Production `.env.production`, созданный из локального шаблона
- SSH-ключ для GitHub Actions

## Подготовка сервера

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
mkdir -p /opt/erp_local
cd /opt/erp_local
git clone https://github.com/amu354084-ops/ecohush.git .
```

Не храните `.env.production` в Git. Перед запуском скопируйте его на сервер защищённым каналом и замените все `CHANGE_ME`.

## Первый запуск

```bash
cd /opt/erp_local
chmod 600 .env.production
docker compose --env-file .env.production -f docker-compose.prod.yml config
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

Приложение доступно на `http://SERVER_IP:1833` до настройки reverse proxy и TLS.

## Миграции PostgreSQL

В текущем приложении схема создаётся при старте. Перед публикацией рекомендуется выполнить миграции отдельно, когда PostgreSQL-контейнер уже healthy:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec web alembic upgrade head
docker compose --env-file .env.production -f docker-compose.prod.yml exec web python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:1833/ready').read().decode())"
```

## Проверка

```bash
curl -fsS http://127.0.0.1:1833/health
curl -fsS http://127.0.0.1:1833/ready
curl -fsS http://127.0.0.1:1833/
```

## GitHub Actions secrets

В репозитории добавьте Actions secrets:

- `DEPLOY_HOST`: IP или DNS VPS
- `DEPLOY_USER`: SSH-пользователь
- `DEPLOY_KEY`: приватный SSH-ключ без passphrase в формате OpenSSH

Убедитесь, что путь `/opt/erp_local` совпадает с сервером.

## TLS

Для публичной публикации не используйте self-signed сертификат. Настройте Nginx на VPS и Let's Encrypt после привязки домена. До этого порт `1833` должен быть закрыт от внешнего доступа firewall-правилом или доступен только через временный whitelist.

## Backup

Проверка backup выполняется внутри web-контейнера:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec web sh /app/scripts/backup_postgres.sh
```

Для S3 заполните `TIMEWEB_S3_BUCKET`, `TIMEWEB_S3_ACCESS_KEY`, `TIMEWEB_S3_SECRET_KEY` и установите AWS CLI в образ/на сервер. После первой копии обязательно выполните тест восстановления на отдельной базе.
