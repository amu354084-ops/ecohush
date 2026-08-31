# Deployment: ERP Local

Этот документ описывает первый запуск на VPS после покупки Timeweb. Локальный SQLite-режим не изменяется.

## Требования

- Ubuntu/Debian VPS
- Docker Engine и Docker Compose plugin
- DNS-запись домена на IP VPS
- Публичный IPv4-адрес VPS (для SSH и первичной проверки)
- Production `.env.production`, созданный из локального шаблона
- SSH-ключ для GitHub Actions

## Шаг 1–2: Подготовка сервера и репозитория

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

## Шаг 3: Подготовка .env.production с секретами

Скопируйте шаблон на сервер и заполните вручную. Все значения, помеченные как **ОБЯЗАТЕЛЬНО**, должны быть установлены перед первым запуском.

### Основные параметры БД (ОБЯЗАТЕЛЬНО)
```
POSTGRES_PASSWORD=<сгенерируйте случайный пароль из 32+ символов>
ERP_AUTH_SECRET=<сгенерируйте случайный ключ из 64+ символов>
ERP_INITIAL_ADMIN_PASSWORD=<выберите надёжный пароль администратора>
```

### Telegram-уведомления (опционально)

Если нужны автоматические уведомления об ошибках:

1. Откройте в Telegram приложение **@BotFather**
2. Выполните команду `/newbot`
3. Следуйте подсказкам, создайте бота, скопируйте **HTTP API Token**
4. Откройте чат **@userinfobot**, нажмите кнопку, скопируйте ваш **ID** (числовое значение)

Пример:
```
TELEGRAM_BOT_TOKEN=123456789:ABCDefGHijKLmnoPQRstUVwxyz1234567890
TELEGRAM_CHAT_ID=987654321
```

### Google Sheets синхронизация (опционально)

Если нужна синхронизация в Google Sheets:

1. Откройте [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте новый проект
3. Включите API: **Google Sheets API** и **Google Drive API**
4. Создайте Service Account: **IAM → Service Accounts → Create Service Account**
5. Сгенерируйте JSON-ключ в разделе **Keys**
6. Скопируйте JSON-файл на сервер: `/opt/erp_local/secrets/google-service-account.json`

Пример:
```
GOOGLE_SHEETS_SPREADSHEET_ID=1ABC123def456ghi789_YourSpreadsheetID
GOOGLE_SHEETS_CREDENTIALS_FILE=/run/secrets/google-service-account.json
GOOGLE_SHEETS_SYNC_MINUTES=720
```

### Timeweb S3 Backup (опционально)

Если нужно бэкапировать базу в облако:

1. Откройте [Timeweb Cabinet](https://cabinet.timeweb.ru/)
2. Перейдите в **Облачное хранилище → S3**
3. Создайте новое хранилище
4. В разделе **Управление ключами**, создайте новый ключ доступа
5. Скопируйте **Access Key** и **Secret Key**

Пример:
```
TIMEWEB_S3_BUCKET=erp-backups-2026
TIMEWEB_S3_ACCESS_KEY=your_access_key
TIMEWEB_S3_SECRET_KEY=your_secret_key
TIMEWEB_S3_REGION=ru-1
TIMEWEB_S3_ENDPOINT=https://s3.timeweb.cloud
```

### Резервное копирование (опционально)
```
BACKUP_DIR=/var/backups/erp
BACKUP_TIMEZONE=UTC
BACKUP_HOUR=23
BACKUP_MINUTE=00
```

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
