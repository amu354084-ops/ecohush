# 🚀 КОНКРЕТНЫЙ ПЛАН РЕАЛИЗАЦИИ для Timeweb VPS

**Статус:** 85% → 100% Ready
**Вариант:** B (3-4 дня, надежный)
**Дата начала:** 2026-08-26
**Ответственный:** Вы + AI Assistant

---

## 📋 ИНФРАСТРУКТУРА

```
Ваша конфигурация:
├─ Хостинг: Timeweb VPS с публичным IPv4
├─ HTTPS: Let's Encrypt после привязки домена
├─ PostgreSQL: Docker контейнер (версия 16)
├─ Backup: Timeweb S3 (S3-compatible)
├─ Мониторинг: Логи + Telegram Alerts
├─ CI/CD: GitHub Actions
├─ Начальный пароль админа: задаётся только на сервере
├─ Email уведомлений: amu354084@gmail.com
└─ Repo: amu354084-ops/ecohush (main branch)
```

---

## 🔴 КРИТИЧЕСКИЕ ДАННЫЕ (нужны сейчас)

Прежде чем начинать, подготовьте:

### 1️⃣ Timeweb VPS Access
- [ ] IP адрес VPS
- [ ] SSH пользователь (обычно `root` или `admin`)
- [ ] SSH пароль или private key
- [ ] Текущий OS (Ubuntu 22.04/20.04, Debian, etc.)

### 2️⃣ Timeweb S3 API (для backup)
- [ ] Endpoint: s3.timeweb.cloud (обычно)
- [ ] Access Key ID
- [ ] Secret Access Key
- [ ] Bucket name (пример: `erp-backups`)
- [ ] Region (пример: `ru-1`)

### 3️⃣ GitHub (для CI/CD позже)
- [x] GitHub username: amu354084-ops
- [x] Repository: ecohush
- [ ] Personal Access Token (создадим позже)

---

## 📊 ТРИ ДНЯ РАБОТЫ

### 🔴 ДЕНЬ 1 (5-6 часов): HTTPS + PostgreSQL + Production Config

#### Этап 1.1: Проверка и подготовка VPS
```bash
# SSH на Timeweb VPS
ssh root@YOUR_VPS_IP

# Проверить Docker установлен ли?
docker --version
docker-compose --version

# Если НЕ установлен:
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Проверить OS
lsb_release -a
```

**Статус задачи: `⚠️ ЖДЁМ ДАННЫЕ`**
*Нужны: IP VPS, SSH доступ, OS версия, статус Docker*

---

#### Этап 1.2: Самоподписанный SSL сертификат (локальный)
```bash
# На VPS или локально - создать сертификат на 1 год
mkdir -p /etc/ssl/private
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/ssl/private/localhost.key \
  -out /etc/ssl/certs/localhost.crt \
  -subj "/CN=localhost"

# Проверить
ls -la /etc/ssl/certs/localhost.crt
ls -la /etc/ssl/private/localhost.key
```

**Статус задачи: ⏳ ЖДЁМ НАЧАЛА**
*Можно начать сразу после SSH доступа*

---

#### Этап 1.3: PostgreSQL в Docker
```bash
# Создать docker-compose.yml с PostgreSQL
cat > docker-compose.yml << 'EOF'
version: '3.9'

services:
  postgres:
    image: postgres:16-alpine
    container_name: erp_postgres
    environment:
      POSTGRES_DB: erp_db
      POSTGRES_USER: erp_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped
    networks:
      - erp_network

  erp_app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: erp_app
    environment:
      DATABASE_URL: postgresql://erp_user:${POSTGRES_PASSWORD}@postgres:5432/erp_db
      ERP_AUTH_SECRET: ${ERP_AUTH_SECRET}
      ERP_INITIAL_ADMIN_PASSWORD: ${ERP_INITIAL_ADMIN_PASSWORD}
      ENVIRONMENT: production
    ports:
      - "443:8000"
    depends_on:
      - postgres
    volumes:
      - /etc/ssl/certs:/etc/ssl/certs:ro
      - /etc/ssl/private:/etc/ssl/private:ro
      - ./logs:/app/logs
    restart: unless-stopped
    networks:
      - erp_network

volumes:
  postgres_data:

networks:
  erp_network:
    driver: bridge
EOF

# Запустить PostgreSQL
docker-compose up -d postgres

# Проверить, что контейнер запущен
docker-compose ps
docker logs erp_postgres
```

**Статус задачи: ⏳ ЖДЁМ НАЧАЛА**
*Нужен docker-compose.yml + .env с паролями*

---

#### Этап 1.4: Production .env (генерировать секреты)
```bash
# Сгенерировать случайные секреты
python3 << 'PYSCRIPT'
import secrets
import string

# ERP_AUTH_SECRET - 32+ символа
auth_secret = secrets.token_urlsafe(32)

# POSTGRES_PASSWORD - надежный пароль
postgres_pwd = secrets.token_urlsafe(24)

# ERP_INITIAL_ADMIN_PASSWORD - начальный пароль (будет вынужденно изменен)
admin_pwd = "admin"  # Вы указали

print(f"ERP_AUTH_SECRET={auth_secret}")
print(f"POSTGRES_PASSWORD={postgres_pwd}")
print(f"ERP_INITIAL_ADMIN_PASSWORD={admin_pwd}")
PYSCRIPT

# Результат скопировать в .env.production
cat > .env.production << 'EOF'
# === Database ===
DATABASE_URL=postgresql://erp_user:YOUR_POSTGRES_PASSWORD@postgres:5432/erp_db
POSTGRES_PASSWORD=YOUR_POSTGRES_PASSWORD

# === Security ===
ERP_AUTH_SECRET=YOUR_AUTH_SECRET_32CHARS
ERP_INITIAL_ADMIN_PASSWORD=admin

# === Environment ===
ENVIRONMENT=production
DEBUG=false

# === Logging ===
LOG_LEVEL=INFO
LOG_FILE=/app/logs/erp.log

# === Telegram (опционально для alerts) ===
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# === Monitoring ===
ENABLE_HEALTH_CHECK=true
HEALTH_CHECK_INTERVAL=60
EOF
```

**Статус задачи: ⏳ ЖДЁМ НАЧАЛА**
*Генерировать прямо сейчас на локальной машине*

---

#### Этап 1.5: Миграции БД (Alembic)
```bash
# На локальной машине с production .env
export DATABASE_URL="postgresql://erp_user:YOUR_POSTGRES_PASSWORD@postgres:5432/erp_db"

# Проверить Alembic статус
alembic current

# Выполнить миграции
alembic upgrade head

# Проверить
alembic history

# Проверить таблицы в БД
psql $DATABASE_URL -c "\dt"
```

**Статус задачи: ⏳ ЖДЁМ PostgreSQL RUNNING**

---

### 🟠 ДЕНЬ 2 (5-6 часов): Health-Check + Backup + CI/CD

#### Этап 2.1: Health-check endpoints
```python
# Добавить в app/api/health_api.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from app.db import get_db

router = APIRouter(tags=["Health"])

@router.get("/health")
async def health_check(db = Depends(get_db)):
    """Базовая проверка здоровья"""
    try:
        await db.execute(text("SELECT 1"))
        return {
            "status": "ok",
            "service": "erp_api",
            "version": "1.0.0"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }, 500

@router.get("/ready")
async def readiness_check(db = Depends(get_db)):
    """Готовность к приему трафика"""
    try:
        result = await db.execute(text("SELECT COUNT(*) FROM users"))
        user_count = result.scalar()

        return {
            "ready": True,
            "database": "connected",
            "users": user_count,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail="Service not ready")

@router.get("/live")
async def liveness_check():
    """Приложение живо и работает"""
    return {
        "alive": True,
        "timestamp": datetime.now().isoformat()
    }

# В app/main.py добавить:
from app.api import health_api
app.include_router(health_api.router)
```

**Статус задачи: ⏳ ЖДЁМ ДЕНЬ 2**

---

#### Этап 2.2: Backup скрипты (pg_dump + Timeweb S3)
```bash
# Создать tools/backup_postgres.sh

#!/bin/bash
set -e

# === КОНФИГУРАЦИЯ ===
POSTGRES_HOST="postgres"
POSTGRES_USER="erp_user"
POSTGRES_DB="erp_db"
POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
BACKUP_DIR="/app/backups"
LOG_FILE="/app/logs/backup.log"

# Timeweb S3
S3_ENDPOINT="s3.timeweb.cloud"
S3_BUCKET="erp-backups"
S3_ACCESS_KEY="$TIMEWEB_S3_ACCESS_KEY"
S3_SECRET_KEY="$TIMEWEB_S3_SECRET_KEY"
S3_REGION="ru-1"

# === ЛОГИРОВАНИЕ ===
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# === СОЗДАНИЕ BACKUP ===
log "Starting PostgreSQL backup..."

BACKUP_FILE="$BACKUP_DIR/erp_backup_$(date +%Y%m%d_%H%M%S).sql.gz"
mkdir -p "$BACKUP_DIR"

PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
    -h "$POSTGRES_HOST" \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    --verbose | gzip > "$BACKUP_FILE"

log "Backup created: $BACKUP_FILE"

# === ЗАГРУЗКА В S3 ===
log "Uploading to Timeweb S3..."

aws s3 cp "$BACKUP_FILE" \
    "s3://$S3_BUCKET/backups/$(basename $BACKUP_FILE)" \
    --endpoint-url "https://$S3_ENDPOINT" \
    --region "$S3_REGION" \
    --access-key "$S3_ACCESS_KEY" \
    --secret-key "$S3_SECRET_KEY" || log "S3 upload failed"

log "Backup completed!"

# === ОЧИСТКА СТАРЫХ ФАЙЛОВ ===
find "$BACKUP_DIR" -type f -mtime +30 -delete  # Удалить старше 30 дней

log "Old backups cleaned"
```

**Статус задачи: ⏳ ЖДЁМ ДЕНЬ 2**

---

#### Этап 2.3: Логирование + Telegram Alerts
```python
# app/services/logging.py

import logging
import json
from datetime import datetime
import requests

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": datetime.now().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

class TelegramHandler(logging.Handler):
    def __init__(self, bot_token: str, chat_id: str):
        super().__init__()
        self.bot_token = bot_token
        self.chat_id = chat_id

    def emit(self, record):
        if record.levelno >= logging.ERROR:
            msg = self.format(record)
            try:
                requests.post(
                    f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                    json={"chat_id": self.chat_id, "text": f"⚠️ ERROR:\n{msg[:1000]}"}
                )
            except:
                pass

def setup_logging(log_file: str, telegram_bot_token: str = None, telegram_chat_id: str = None):
    logger = logging.getLogger("erp")
    logger.setLevel(logging.INFO)

    # JSON файл логов
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)

    # Telegram alerts для ошибок
    if telegram_bot_token and telegram_chat_id:
        tg_handler = TelegramHandler(telegram_bot_token, telegram_chat_id)
        tg_handler.setLevel(logging.ERROR)
        logger.addHandler(tg_handler)

    return logger
```

**Статус задачи: ⏳ ЖДЁМ ДЕНЬ 2**

---

#### Этап 2.4: GitHub Actions CI/CD Pipeline
```yaml
# .github/workflows/deploy.yml

name: Deploy to Production

on:
  push:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_PASSWORD: test_password
          POSTGRES_DB: test_db
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run backend tests
        env:
          DATABASE_URL: postgresql://postgres:test_password@localhost:5432/test_db
        run: python -m pytest -q

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '18'

      - name: Run E2E tests
        run: npm run test:e2e

  build:
    needs: test
    runs-on: ubuntu-latest

    permissions:
      contents: read
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Build and push Docker image
        run: |
          docker build -t ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest .
          # Push будет настроен после указания GHCR токена

  deploy:
    needs: build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'

    steps:
      - name: Deploy to production
        env:
          DEPLOY_KEY: ${{ secrets.DEPLOY_KEY }}
          DEPLOY_HOST: ${{ secrets.DEPLOY_HOST }}
          DEPLOY_USER: ${{ secrets.DEPLOY_USER }}
        run: |
          # Пример деплоя через SSH
          echo "$DEPLOY_KEY" > /tmp/deploy_key
          chmod 600 /tmp/deploy_key
          ssh -i /tmp/deploy_key $DEPLOY_USER@$DEPLOY_HOST << 'DEPLOY_EOF'
            cd /app/erp
            git pull origin main
            docker-compose pull
            docker-compose up -d
          DEPLOY_EOF
```

**Статус задачи: ⏳ ЖДЁМ GITHUB REPO**

---

### 🟡 ДЕНЬ 3 (3-4 часа): Документация + Финальные тесты

#### Этап 3.1: DEPLOYMENT.md
```markdown
# 📋 DEPLOYMENT Guide

## Pre-deployment Checklist
- [ ] Все тесты проходят
- [ ] PostgreSQL работает
- [ ] .env.production заполнен
- [ ] SSL сертификат готов
- [ ] Backup скрипты работают
- [ ] Логирование настроено

## Deployment Steps

### 1. Подготовка VPS
\`\`\`bash
ssh root@YOUR_VPS_IP
cd /app/erp
docker-compose pull
docker-compose down
\`\`\`

### 2. Запуск
\`\`\`bash
docker-compose up -d
docker-compose ps
docker logs -f erp_app
\`\`\`

### 3. Проверка
\`\`\`bash
curl -k https://localhost/health
curl -k https://localhost/ready
curl -k https://localhost/live
\`\`\`

## Rollback на предыдущую версию
\`\`\`bash
docker-compose down
# Восстановить из backup
alembic downgrade -1
docker-compose up -d
\`\`\`
```

---

#### Этап 3.2: Smoke Tests
```bash
# Проверить что все работает

# 1. Health checks
curl -k https://localhost/health
curl -k https://localhost/ready
curl -k https://localhost/live

# 2. Login
curl -X POST https://localhost/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"admin"}' \
  -k

# 3. API tests
pytest tests/ -v

# 4. E2E tests
npm run test:e2e
```

---

## 📝 CHECKLIST ПО ДНЯМ

### День 1 ✅
- [ ] SSH доступ на VPS
- [ ] Docker установлен
- [ ] PostgreSQL контейнер запущен
- [ ] .env.production создан
- [ ] Миграции выполнены (alembic upgrade head)
- [ ] Локальные тесты проходят

**Результат дня 1:** ✅ Приложение работает с PostgreSQL

---

### День 2 ✅
- [ ] Health-check endpoints готовы (/health, /ready, /live)
- [ ] Backup скрипты работают
- [ ] Логирование включено (JSON + Telegram)
- [ ] GitHub Actions pipeline создан
- [ ] Docker image собран

**Результат дня 2:** ✅ Мониторинг + CI/CD готовы

---

### День 3 ✅
- [ ] DEPLOYMENT.md написана
- [ ] RUNBOOK.md написана
- [ ] Smoke tests пройдены
- [ ] Team обучена
- [ ] Документация обновлена

**Результат дня 3:** ✅ 100% Production Ready!

---

## 🚀 СТАТУС ПРОГРЕССА

```
Начало:           85% ✅
День 1 конец:     90% ✅ (HTTPS, PostgreSQL, .env)
День 2 конец:     97% ✅ (Health-check, Backup, CI/CD)
День 3 конец:    100% 🚀 (Документация, Тесты, READY!)
```

---

## 💬 ВОПРОСЫ - ПОЛУЧЕНИЕ ПОМОЩИ

На каждом этапе вы можете задавать вопросы:
- "Как настроить Timeweb S3 API?"
- "Ошибка при запуске PostgreSQL"
- "Как откатить если что-то не сработало?"
- "Как настроить Telegram alerts?"

AI Assistant будет помогать на каждом этапе! 🤖

---

## 🎯 ФИНАЛЬНЫЙ РЕЗУЛЬТАТ

После завершения всех 10 задач вы получите:

✅ 100% Production-ready систему
✅ Самоподписанный HTTPS (локальный)
✅ PostgreSQL 16 в Docker
✅ Надежные автоматические backup в S3
✅ Мониторинг + Telegram alerts
✅ Полностью автоматизированный CI/CD
✅ Документация для team
✅ Готовность к масштабированию

---

**Начнем? Какой следующий этап вы хотите начать с?**

Вариант 1️⃣: "Начинаем с Дня 1, Этап 1.1 - проверка VPS"
Вариант 2️⃣: "Хочу сразу скопировать все скрипты локально"
Вариант 3️⃣: "Нужна помощь с собиранием данных Timeweb"

**Готовы? Давайте делать! 🚀**
