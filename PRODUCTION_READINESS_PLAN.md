# 🚀 План Достижения 100% Готовности к Production

**Текущий статус:** 85% ✅
**Целевой статус:** 100% 🎯
**Дата начала:** 2026-08-26

---

## 📋 Сводка Оставшихся Работ

| Приоритет | Область | Трудоёмкость | Статус |
|-----------|--------|-------------|--------|
| 🔴 КРИТИЧНО | HTTPS + TLS | 3 часа | ⏳ В очереди |
| 🔴 КРИТИЧНО | PostgreSQL интеграция | 5 часов | ⏳ В очереди |
| 🔴 КРИТИЧНО | Production `.env` | 2 часа | ⏳ В очереди |
| 🟠 ВЫСОКИЙ | CI/CD расширение | 4 часа | ⏳ В очереди |
| 🟠 ВЫСОКИЙ | Health-check улучшение | 2 часа | ⏳ В очереди |
| 🟠 ВЫСОКИЙ | Backup/Restore процедуры | 3 часа | ⏳ В очереди |
| 🟡 СРЕДНИЙ | Документация deployment | 3 часа | ⏳ В очереди |
| 🟡 СРЕДНИЙ | Логирование и мониторинг | 2 часа | ⏳ В очереди |
| 🟢 НИЗКИЙ | Performance оптимизация | 4 часа | ⏳ В очереди |

**Общая трудоёмкость:** ~28 часов / ~3-4 дня

---

## 🔴 КРИТИЧЕСКИЕ РАБОТЫ (Обязательны для Production)

### 1️⃣ HTTPS + TLS Конфигурация (3 часа)

**Цель:** Все коммуникации должны быть зашифрованы

#### 1.1 Выбрать метод HTTPS
```
Вариант A: Nginx + Let's Encrypt (РЕКОМЕНДУЕТСЯ)
├─ Простая настройка
├─ Автоматический renewal сертификатов
├─ Production-ready
└─ Стоимость: $0

Вариант B: Caddy (АЛЬТЕРНАТИВА)
├─ Автоматический HTTPS с Let's Encrypt
├─ Меньше конфигурации
└─ Хороший выбор для small/medium

Вариант C: Cloudflare (Если используется)
├─ Proxying + SSL
├─ DDoS защита
└─ Платное

Вариант D: Встроенный Uvicorn SSL (НЕ РЕКОМЕНДУЕТСЯ)
├─ Сложная валидация сертификатов
└─ Требует перезапуска при обновлении
```

#### 1.2 Nginx конфигурация (для Вариант A)

**Файл:** `nginx.conf`
```nginx
upstream erp_backend {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Modern configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location / {
        proxy_pass http://erp_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $server_name;
        proxy_redirect off;
    }
}
```

#### 1.3 Получение SSL сертификата

```bash
# Установка Certbot
sudo apt-get install certbot python3-certbot-nginx

# Получение сертификата для вашего домена
sudo certbot certonly --nginx -d your-domain.com -d www.your-domain.com

# Автоматический renewal (добавится в cron)
sudo certbot renew --dry-run
```

#### 1.4 Docker конфигурация с Nginx

**Файл:** `docker-compose.prod.yml`
```yaml
version: '3.8'

services:
  erp-app:
    build: .
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/erp_prod
      - ERP_AUTH_SECRET=${ERP_AUTH_SECRET}
      - ERP_INITIAL_ADMIN_PASSWORD=${ERP_INITIAL_ADMIN_PASSWORD}
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      - postgres
    volumes:
      - ./backups:/app/backups

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: erp_prod
      POSTGRES_USER: erp_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - erp-app

volumes:
  postgres_data:
```

#### ✅ Чек-лист HTTPS
- [ ] SSL сертификат получен и установлен
- [ ] Nginx конфигурирован правильно
- [ ] Редирект с HTTP на HTTPS работает
- [ ] Security headers установлены
- [ ] E2E тесты работают на HTTPS
- [ ] Все API вызовы через HTTPS

---

### 2️⃣ PostgreSQL Интеграция (5 часов)

**Цель:** Переключиться с SQLite на PostgreSQL для production

#### 2.1 Установка PostgreSQL

```bash
# Ubuntu/Debian
sudo apt-get install postgresql postgresql-contrib

# Или использовать Docker
docker run -d \
  -e POSTGRES_DB=erp_prod \
  -e POSTGRES_USER=erp_user \
  -e POSTGRES_PASSWORD=SecurePassword123! \
  -p 5432:5432 \
  -v postgres_data:/var/lib/postgresql/data \
  postgres:16-alpine
```

#### 2.2 Подготовка БД

```bash
# Подключиться к PostgreSQL
psql -U erp_user -d erp_prod -h localhost

# Создать необходимые extensions
CREATE EXTENSION IF NOT EXISTS uuid-ossp;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

# Выполнить начальную миграцию
alembic upgrade head
```

#### 2.3 Обновить конфигурацию приложения

**Файл:** `app/db.py` (уже готово, просто проверить)
```python
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'sqlite:///./erp.db'  # Fallback для dev
)

# Если используется SQLite, добавить специальные настройки
if DATABASE_URL.startswith('sqlite'):
    engine = create_engine(
        DATABASE_URL,
        connect_args={'check_same_thread': False},
        pool_pre_ping=True
    )
else:  # PostgreSQL
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

#### 2.4 Создать production `.env.production`

```bash
# Database
DATABASE_URL=postgresql://erp_user:SecurePassword123!@postgres.example.com:5432/erp_prod

# Auth
ERP_AUTH_SECRET=<Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))">
ERP_INITIAL_ADMIN_PASSWORD=<Strong password here>

# Server
ERP_SERVER_PORT=8000
ERP_DISABLE_INITIAL_PASSWORD_CHANGE=0

# Backup
BACKUP_ENABLED=1
BACKUP_SCHEDULE=0 2 * * *  # 2 AM every day
BACKUP_RETENTION_DAYS=30
```

#### 2.5 Тестирование PostgreSQL

```bash
# Запустить тесты с PostgreSQL
export DATABASE_URL=postgresql://erp_user:pass@localhost/erp_test
pytest -q

# Проверить миграции
alembic current
alembic upgrade head

# Проверить данные
psql -U erp_user -d erp_prod -c "SELECT COUNT(*) FROM users;"
```

#### ✅ Чек-лист PostgreSQL
- [ ] PostgreSQL установлен и запущен
- [ ] База данных создана с правильными permissions
- [ ] Миграции Alembic выполнены успешно
- [ ] Тесты проходят с PostgreSQL (не SQLite)
- [ ] Performance адекватен (query <100ms)
- [ ] Backup работает с pg_dump

---

### 3️⃣ Production `.env` Конфигурация (2 часа)

**Цель:** Безопасно управлять секретами в production

#### 3.1 Создать `.env.production.example` (для документации)

```bash
# ==== Database ====
DATABASE_URL=postgresql://erp_user:CHANGE_ME@postgres.example.com:5432/erp_prod

# ==== Auth & Security ====
ERP_AUTH_SECRET=CHANGE_ME_32_CHARACTERS_MINIMUM
ERP_INITIAL_ADMIN_PASSWORD=CHANGE_ME_STRONG_PASSWORD

# ==== Backup ====
BACKUP_ENABLED=1
BACKUP_SCHEDULE=0 2 * * *
BACKUP_RETENTION_DAYS=30
BACKUP_DESTINATION=s3://your-bucket/backups/

# ==== Logging ====
LOG_LEVEL=INFO
LOG_FORMAT=json

# ==== Server ====
ERP_SERVER_PORT=8000
WORKERS=4
```

#### 3.2 Методы управления секретами

**Вариант 1: Vault (HashiCorp) - РЕКОМЕНДУЕТСЯ**
```bash
# Установить Vault
# Получить секреты при запуске приложения
python -c "
from hvac import Client
client = Client(url='https://vault.example.com')
secrets = client.secrets.kv.read_secret_version('secret/erp/prod')
print(secrets['data']['data'])
"
```

**Вариант 2: AWS Secrets Manager**
```python
import boto3
import json

def get_secrets():
    client = boto3.client('secretsmanager', region_name='us-east-1')
    response = client.get_secret_value(SecretId='erp/prod')
    return json.loads(response['SecretString'])
```

**Вариант 3: Docker Secrets (Если используется Swarm)**
```bash
# Создать secret
docker secret create db_password -

# Использовать в service
docker service create \
  -e DATABASE_PASSWORD_FILE=/run/secrets/db_password \
  ...
```

**Вариант 4: Environment variables (Простой вариант)**
```bash
# В production контейнере установить через:
docker run -e ERP_AUTH_SECRET=... -e DATABASE_URL=...
# Или в docker-compose через .env.prod файл
```

#### 3.3 Генерация безопасных паролей

```bash
# Генерировать секреты
python -c "
import secrets
import string

# Для ERP_AUTH_SECRET (32+ символа)
auth_secret = secrets.token_urlsafe(32)
print(f'ERP_AUTH_SECRET={auth_secret}')

# Для ADMIN_PASSWORD (требует A-Z, a-z, 0-9, спецсимволы)
def gen_password():
    chars = string.ascii_letters + string.digits + '!@#$%^&*'
    return ''.join(secrets.choice(chars) for _ in range(16))

print(f'ERP_INITIAL_ADMIN_PASSWORD={gen_password()}')

# Для DB_PASSWORD
print(f'POSTGRES_PASSWORD={secrets.token_urlsafe(24)}')
"
```

#### 3.4 Проверка конфигурации перед запуском

```python
# app/config.py
import os
from typing import List

REQUIRED_ENV_VARS: List[str] = [
    'DATABASE_URL',
    'ERP_AUTH_SECRET',
    'ERP_INITIAL_ADMIN_PASSWORD',
]

def check_production_config():
    """Проверить что все обязательные переменные установлены"""
    missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing:
        raise ValueError(f"Missing required env vars: {missing}")

    # Проверить длину SECRET
    secret = os.getenv('ERP_AUTH_SECRET', '')
    if len(secret) < 32:
        raise ValueError(f"ERP_AUTH_SECRET must be at least 32 characters")

    # Проверить что DATABASE_URL не содержит пароль в открытом виде в логах
    db_url = os.getenv('DATABASE_URL', '')
    if 'sqlite' in db_url:
        raise ValueError("SQLite not allowed in production")

# Вызвать при запуске приложения
if os.getenv('ENVIRONMENT') == 'production':
    check_production_config()
```

#### ✅ Чек-лист Конфигурации
- [ ] `.env.production` создан и заполнен
- [ ] Все обязательные переменные установлены
- [ ] Пароли соответствуют требованиям безопасности
- [ ] Проверка конфигурации работает
- [ ] Секреты не видны в логах
- [ ] Backup переменные настроены

---

## 🟠 ВЫСОКИЕ ПРИОРИТЕТЫ (Важны для Production)

### 4️⃣ CI/CD Расширение (4 часа)

**Цель:** Автоматизировать testing и deployment

#### 4.1 GitHub Actions с PostgreSQL

**Файл:** `.github/workflows/production-deploy.yml`
```yaml
name: Production Deployment

on:
  push:
    branches: [main]
  workflow_dispatch:

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
          POSTGRES_DB: test_db
          POSTGRES_USER: test_user
          POSTGRES_PASSWORD: test_pass
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
          DATABASE_URL: postgresql://test_user:test_pass@localhost/test_db
        run: pytest -q --tb=short

      - name: Run E2E tests
        run: npm run test:e2e

      - name: Build Docker image
        run: docker build -t ${{ env.IMAGE_NAME }}:latest .

      - name: Push to registry
        run: |
          echo ${{ secrets.GITHUB_TOKEN }} | docker login -u ${{ github.actor }} --password-stdin ${{ env.REGISTRY }}
          docker tag ${{ env.IMAGE_NAME }}:latest ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest
          docker push ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest

  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: success()

    steps:
      - name: Deploy to production
        env:
          DEPLOY_KEY: ${{ secrets.DEPLOY_KEY }}
          DEPLOY_HOST: ${{ secrets.DEPLOY_HOST }}
          DEPLOY_USER: ${{ secrets.DEPLOY_USER }}
        run: |
          mkdir -p ~/.ssh
          echo "$DEPLOY_KEY" > ~/.ssh/deploy_key
          chmod 600 ~/.ssh/deploy_key
          ssh-keyscan -H ${{ env.DEPLOY_HOST }} >> ~/.ssh/known_hosts
          ssh -i ~/.ssh/deploy_key ${{ env.DEPLOY_USER }}@${{ env.DEPLOY_HOST }} "cd /app && docker-compose pull && docker-compose up -d"
```

#### 4.2 Проверка конфигурации Docker

```bash
# Создать Dockerfile с prod оптимизацией
docker build --target production -t erp-prod:latest .

# Проверить размер образа
docker images erp-prod

# Проверить запуск с миграциями
docker run --rm \
  -e DATABASE_URL=postgresql://... \
  -e ERP_AUTH_SECRET=... \
  erp-prod:latest \
  alembic upgrade head
```

#### ✅ Чек-лист CI/CD
- [ ] GitHub Actions workflow создан
- [ ] PostgreSQL тесты проходят в CI
- [ ] Docker build проходит
- [ ] E2E тесты запускаются в CI
- [ ] Автоматический deployment настроен
- [ ] Rollback процедура документирована

---

### 5️⃣ Health-Check Улучшение (2 часа)

**Цель:** Расширить проверку здоровья приложения

#### 5.1 Улучшенный health endpoint

**Файл:** `app/api/health_api.py` (добавить)
```python
from fastapi import APIRouter, Response
from sqlalchemy import text
import time

router = APIRouter()

# Для хранения времени запуска приложения
_startup_time = time.time()

@router.get('/health', tags=['system'])
async def health_check(db=Depends(get_db)):
    """Быстрая проверка работоспособности (используется балансировщиком)"""
    try:
        # Проверка БД (простой запрос)
        db.execute(text('SELECT 1'))
        return {
            'status': 'ok',
            'timestamp': time.time(),
            'uptime': time.time() - _startup_time
        }
    except Exception as e:
        return Response(
            content='{"status": "error"}',
            status_code=503,
            media_type='application/json'
        )

@router.get('/ready', tags=['system'])
async def readiness_check(db=Depends(get_db)):
    """Полная проверка готовности приложения"""
    checks = {}

    try:
        # Проверка БД
        result = db.execute(text('SELECT version()'))
        checks['database'] = 'ok'
    except Exception as e:
        checks['database'] = f'error: {str(e)}'

    try:
        # Проверка миграций
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext

        # Получить текущую ревизию
        mc = MigrationContext.configure(db.connection())
        current_rev = mc.get_current_revision()

        # Получить последнюю ревизию
        config = Config('alembic.ini')
        script = ScriptDirectory.from_config(config)
        head_rev = script.get_current_head()

        checks['migrations'] = 'ok' if current_rev == head_rev else f'pending: {head_rev}'
    except Exception as e:
        checks['migrations'] = f'error: {str(e)}'

    try:
        # Проверка таблиц
        essential_tables = ['users', 'clients', 'orders', 'sales']
        for table in essential_tables:
            db.execute(text(f'SELECT 1 FROM {table} LIMIT 1'))
        checks['tables'] = 'ok'
    except Exception as e:
        checks['tables'] = f'error: {str(e)}'

    # Определить общий статус
    all_ok = all(v == 'ok' for v in checks.values())

    return {
        'status': 'ready' if all_ok else 'degraded',
        'checks': checks,
        'timestamp': time.time()
    }

@router.get('/live', tags=['system'])
async def liveness_check():
    """Проверка что приложение живо (используется для перезагрузки)"""
    return {'status': 'alive'}
```

#### 5.2 Kubernetes readiness/liveness probes

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: erp-app
spec:
  template:
    spec:
      containers:
      - name: erp
        livenessProbe:
          httpGet:
            path: /live
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
```

#### ✅ Чек-лист Health-Check
- [ ] `/health` endpoint работает
- [ ] `/ready` endpoint проверяет все компоненты
- [ ] `/live` endpoint для liveness probe
- [ ] Миграции проверяются в readiness
- [ ] Балансировщик использует правильный endpoint
- [ ] Мониторинг отслеживает health metrics

---

### 6️⃣ Backup & Restore Процедуры (3 часа)

**Цель:** Надёжное восстановление после сбоев

#### 6.1 Автоматический PostgreSQL backup

**Файл:** `tools/backup_postgres.sh`
```bash
#!/bin/bash

# Настройки
DB_NAME=${POSTGRES_DB:-erp_prod}
DB_USER=${POSTGRES_USER:-erp_user}
DB_HOST=${POSTGRES_HOST:-localhost}
DB_PORT=${POSTGRES_PORT:-5432}
BACKUP_DIR=${BACKUP_DIR:-./backups}
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-30}

# Создать директорию
mkdir -p $BACKUP_DIR

# Генерировать имя файла
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/erp_${TIMESTAMP}.sql.gz"

# Выполнить backup
export PGPASSWORD=$POSTGRES_PASSWORD
pg_dump -h $DB_HOST -p $DB_PORT -U $DB_USER $DB_NAME | gzip > $BACKUP_FILE

if [ $? -eq 0 ]; then
    echo "[$(date)] Backup успешен: $BACKUP_FILE"

    # Удалить старые backups
    find $BACKUP_DIR -name "erp_*.sql.gz" -mtime +$RETENTION_DAYS -delete
    echo "[$(date)] Старые backups удалены (старше $RETENTION_DAYS дней)"
else
    echo "[$(date)] ОШИБКА: Backup не удался!"
    exit 1
fi

# Очистить переменную с паролем
unset PGPASSWORD
```

#### 6.2 Cron job для автоматического backup

```bash
# Добавить в crontab
# Запускать backup каждый день в 2 AM
0 2 * * * /app/tools/backup_postgres.sh >> /var/log/erp_backup.log 2>&1

# Запускать проверку backup каждый час
0 * * * * /app/tools/verify_backup.sh
```

#### 6.3 Процедура восстановления

**Файл:** `tools/restore_postgres.sh`
```bash
#!/bin/bash

# Использование: ./restore_postgres.sh backup_file.sql.gz

if [ -z "$1" ]; then
    echo "Использование: $0 backup_file.sql.gz"
    exit 1
fi

BACKUP_FILE=$1
DB_NAME=${POSTGRES_DB:-erp_prod}
DB_USER=${POSTGRES_USER:-erp_user}
DB_HOST=${POSTGRES_HOST:-localhost}

echo "⚠️  ВНИМАНИЕ: Это удалит текущую БД и восстановит из backup!"
read -p "Продолжить? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Отменено."
    exit 0
fi

export PGPASSWORD=$POSTGRES_PASSWORD

# Удалить текущую БД
dropdb -h $DB_HOST -U $DB_USER $DB_NAME

# Создать новую БД
createdb -h $DB_HOST -U $DB_USER $DB_NAME

# Восстановить из backup
gunzip -c $BACKUP_FILE | psql -h $DB_HOST -U $DB_USER $DB_NAME

if [ $? -eq 0 ]; then
    echo "✅ Восстановление завершено успешно!"
else
    echo "❌ Ошибка восстановления!"
    exit 1
fi

unset PGPASSWORD
```

#### 6.4 Тестирование backup/restore

```bash
# Создать backup
./tools/backup_postgres.sh

# Проверить что файл создан
ls -lh backups/

# Проверить содержимое backup
zcat backups/erp_*.sql.gz | head -20

# На тестовой БД: восстановить и проверить
./tools/restore_postgres.sh backups/erp_*.sql.gz
psql -U erp_user -d erp_prod -c "SELECT COUNT(*) FROM users;"
```

#### ✅ Чек-лист Backup
- [ ] Backup script создан и работает
- [ ] Cron job настроен
- [ ] Backup файлы хранятся в безопасном месте (не на том же сервере!)
- [ ] Restore script работает
- [ ] Restore процесс протестирован
- [ ] Удаление старых backups работает

---

## 🟡 СРЕДНИЕ ПРИОРИТЕТЫ (Нужны для надёжности)

### 7️⃣ Документация Deployment (3 часа)

Создать файлы:

**Файл:** `DEPLOYMENT.md`
```markdown
# Инструкция Deployment

## Предварительные требования

- Docker и Docker Compose
- PostgreSQL 16+
- Nginx для HTTPS
- SSL сертификат от Let's Encrypt

## Этапы Deployment

### 1. Подготовка сервера

```bash
# Установить Docker
curl -fsSL https://get.docker.com | sh

# Установить Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Установить Nginx
sudo apt-get install nginx certbot python3-certbot-nginx

# Клонировать репозиторий
git clone <url> /app/erp
cd /app/erp
```

### 2. Настройка конфигурации

```bash
# Создать production .env
cp .env.production.example .env.production

# Отредактировать:
# - DATABASE_URL
# - ERP_AUTH_SECRET
# - ERP_INITIAL_ADMIN_PASSWORD
nano .env.production

# Получить SSL сертификат
sudo certbot certonly --nginx -d your-domain.com
```

### 3. Запуск приложения

```bash
# Запустить контейнеры
docker-compose -f docker-compose.prod.yml up -d

# Проверить логи
docker-compose -f docker-compose.prod.yml logs -f erp-app

# Проверить health
curl https://your-domain.com/health
```

### 4. Проверка

```bash
# Проверить миграции
curl https://your-domain.com/ready

# Проверить admin access
curl -X POST https://your-domain.com/api/v1/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"..."}'

# Проверить backup
docker-compose -f docker-compose.prod.yml exec postgres pg_dump ... | gzip > backup.sql.gz
```

## Мониторинг

### Логи

```bash
# Логи приложения
docker-compose logs -f erp-app

# Логи Nginx
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Логи PostgreSQL
docker-compose logs -f postgres
```

### Health checks

```bash
# Каждый час
0 * * * * curl -f https://your-domain.com/ready || alert "ERP down"
```

## Обновление

```bash
# Получить новую версию
git pull origin main

# Пересобрать контейнер
docker-compose -f docker-compose.prod.yml build --no-cache

# Выполнить миграции
docker-compose -f docker-compose.prod.yml exec erp-app alembic upgrade head

# Перезагрузить приложение
docker-compose -f docker-compose.prod.yml up -d
```

## Откат

```bash
# Откатить к предыдущей версии
git checkout <previous-commit>
docker-compose -f docker-compose.prod.yml up -d

# Откатить БД миграцию (если нужно)
alembic downgrade -1
```

## Troubleshooting

### "Connection refused"
- Проверить что PostgreSQL запущен: `docker-compose ps`
- Проверить переменные окружения в `.env.production`

### "502 Bad Gateway"
- Проверить логи приложения: `docker-compose logs erp-app`
- Проверить что приложение запущено: `docker-compose ps`

### "SSL certificate error"
- Проверить сертификат: `certbot certificates`
- Обновить: `certbot renew --dry-run`
```

**Файл:** `ROLLBACK.md`
```markdown
# Процедура Экстренного Отката

## Быстрый откат (5 минут)

```bash
# 1. Остановить текущую версию
docker-compose -f docker-compose.prod.yml down

# 2. Вернуться к предыдущему коммиту
git checkout <previous-commit>

# 3. Пересобрать и запустить
docker-compose -f docker-compose.prod.yml build
docker-compose -f docker-compose.prod.yml up -d

# 4. Проверить
curl https://your-domain.com/ready
```

## Откат БД

Если нужно откатить миграцию:

```bash
# Найти предыдущую версию
alembic history

# Откатить на шаг назад
alembic downgrade -1

# Или на конкретную версию
alembic downgrade <revision>

# Проверить
alembic current
```
```

#### ✅ Чек-лист Документации
- [ ] DEPLOYMENT.md создан и актуален
- [ ] ROLLBACK.md готов к использованию
- [ ] Все команды протестированы
- [ ] Переменные окружения документированы
- [ ] Troubleshooting раздел полный
- [ ] Процедура backup документирована

---

### 8️⃣ Логирование и Мониторинг (2 часа)

#### 8.1 Структурированное логирование

**Файл:** `app/logging_config.py`
```python
import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_data)

def setup_logging():
    handler = logging.StreamHandler()
    formatter = JSONFormatter()
    handler.setFormatter(formatter)

    logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)

    return logging.getLogger(__name__)
```

#### 8.2 Application Performance Monitoring (APM)

```python
# app/main.py

from prometheus_client import Counter, Histogram, generate_latest
from fastapi.responses import Response
import time

# Метрики
request_count = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

request_duration = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration',
    ['method', 'endpoint']
)

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.time()

    response = await call_next(request)

    duration = time.time() - start
    endpoint = request.url.path

    request_count.labels(
        method=request.method,
        endpoint=endpoint,
        status=response.status_code
    ).inc()

    request_duration.labels(
        method=request.method,
        endpoint=endpoint
    ).observe(duration)

    return response

@app.get('/metrics')
async def metrics():
    return Response(content=generate_latest(), media_type='text/plain')
```

#### ✅ Чек-лист Логирования
- [ ] JSON логирование установлено
- [ ] Логи отправляются в ELK/CloudWatch/etc.
- [ ] Метрики Prometheus собираются
- [ ] Alert rules настроены
- [ ] Dashboards в Grafana созданы
- [ ] Логи ротируются

---

## 🟢 НИЗКИЕ ПРИОРИТЕТЫ (Nice-to-have для Production)

### 9️⃣ Performance Оптимизация (4 часа)

#### 9.1 Кэширование на уровне БД

```python
from sqlalchemy import text
from functools import lru_cache

@lru_cache(maxsize=100)
def get_client_by_id(client_id: int):
    # Кэшировать результаты на 5 минут
    pass
```

#### 9.2 Индексы БД

```sql
-- Часто используемые поля
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_client_id ON orders(client_id);
CREATE INDEX idx_sales_order_id ON sales(order_id);
CREATE INDEX idx_inventory_product_id ON inventory(product_id);

-- Полнотекстовый поиск
CREATE INDEX idx_clients_name ON clients USING GIN (to_tsvector('russian', name));
```

#### 9.3 Connection pooling

```python
# app/db.py
engine = create_engine(
    DATABASE_URL,
    pool_size=20,           # Одновременные подключения
    max_overflow=10,        # Дополнительные подключения
    pool_recycle=3600,      # Пересоздавать каждый час
    pool_pre_ping=True      # Проверять соединение перед использованием
)
```

---

## ✅ ИТОГОВЫЙ ЧЕК-ЛИСТ ДЛЯ 100% ГОТОВНОСТИ

### ОБЯЗАТЕЛЬНЫЕ (Критично)
- [ ] HTTPS конфигурирован и работает
- [ ] PostgreSQL установлен и протестирован
- [ ] Production `.env` создан с безопасными паролями
- [ ] Все тесты проходят с PostgreSQL
- [ ] Миграции Alembic применяются автоматически

### ОЧЕНЬ ВАЖНЫЕ (High)
- [ ] CI/CD pipeline настроен на GitHub Actions
- [ ] Docker build и deployment работают
- [ ] Backup процедуры протестированы
- [ ] Health-check endpoints работают
- [ ] E2E тесты проходят в CI

### ВАЖНЫЕ (Medium)
- [ ] Deployment документация полная
- [ ] Logging система работает
- [ ] Мониторинг и алерты настроены
- [ ] Rollback процедура задокументирована
- [ ] SSL сертификат автоматически обновляется

### УЛУЧШЕНИЯ (Low)
- [ ] Performance оптимизирована
- [ ] Кэширование реализовано
- [ ] Индексы БД добавлены
- [ ] APM метрики собираются
- [ ] Документация по API полная

---

## 📊 Прогресс Roadmap

```
Текущий статус: ████████████████░░░░░░░ 85%

После критических работ: █████████████████████░ 95%
  ├─ HTTPS ........................ +5%
  ├─ PostgreSQL .................. +5%
  └─ Production .env ............. +5%

После высоких приоритетов: ███████████████████████ 100%
  ├─ CI/CD ....................... +3%
  ├─ Health-check ................ +1%
  └─ Backup/Restore .............. +1%
```

---

## 🚀 Рекомендуемый График

| Фаза | День | Работы | Статус |
|------|------|--------|--------|
| **Подготовка** | День 1 | HTTPS + PostgreSQL + Env | 🎯 Критично |
| **Интеграция** | День 2 | CI/CD + Health-check | 🎯 Высокий |
| **Надёжность** | День 3 | Backup + Документация | 🎯 Средний |
| **Оптимизация** | День 4 | Performance + Мониторинг | 🎯 Низкий |
| **Финальная проверка** | День 5 | Smoke tests + Production check | ✅ Готово |

---

**Общая трудоёмкость:** 3-5 дней для команды из 1-2 человек

**Результат:** Проект готов к надёжному production deployment! 🚀
