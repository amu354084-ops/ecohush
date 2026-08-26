# ⚡ Быстрый Старт - 100% Production Readiness

**Что нужно делать ПО ПОРЯДКУ, чтобы выпустить в production**

---

## 🎯 ЭТАП 1: Критические работы (День 1)

### Задача 1: HTTPS + SSL сертификат (1-2 часа)

**Что делать:**
1. Получить домен (если ещё нет)
2. Установить Let's Encrypt сертификат
3. Настроить Nginx для HTTPS редиректа

**Быстрый способ:**
```bash
# На VPS/Server запустить:
sudo apt-get update && sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo certbot certonly --standalone -d your-domain.com -d www.your-domain.com

# Скопировать nginx.conf из документации
sudo cp /app/nginx.conf /etc/nginx/sites-enabled/default
sudo systemctl start nginx
```

**Проверить:**
```bash
curl https://your-domain.com/health
# Должен вернуть 200 с {"status":"ok"}
```

---

### Задача 2: PostgreSQL вместо SQLite (2-3 часа)

**Что делать:**
1. Выбрать хостинг PostgreSQL (AWS RDS / DigitalOcean / Heroku / VPS)
2. Создать базу данных
3. Обновить `DATABASE_URL` в `.env`
4. Выполнить миграции

**Быстрый способ (если Docker на VPS):**
```bash
# Запустить PostgreSQL в Docker
docker run -d \
  --name erp-postgres \
  -e POSTGRES_DB=erp_prod \
  -e POSTGRES_USER=erp_user \
  -e POSTGRES_PASSWORD=SECURE_PASSWORD_HERE \
  -p 5432:5432 \
  -v postgres_data:/var/lib/postgresql/data \
  postgres:16-alpine

# Проверить что БД работает
docker exec erp-postgres psql -U erp_user -d erp_prod -c "SELECT version();"
```

**Обновить конфигурацию:**
```bash
# В .env.production:
DATABASE_URL=postgresql://erp_user:SECURE_PASSWORD_HERE@localhost:5432/erp_prod
```

**Выполнить миграции:**
```bash
# Локально или в контейнере
alembic upgrade head

# Проверить
alembic current
```

**Проверить что тесты проходят:**
```bash
export DATABASE_URL=postgresql://erp_user:SECURE_PASSWORD_HERE@localhost:5432/erp_prod
pytest -q
```

---

### Задача 3: Production конфигурация (30 минут)

**Что делать:**
1. Сгенерировать безопасные секреты
2. Создать `.env.production`
3. Проверить что приложение запускается

**Быстрый способ:**
```bash
# Сгенерировать секреты
python -c "
import secrets
print('ERP_AUTH_SECRET=' + secrets.token_urlsafe(32))
print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))
print('ERP_INITIAL_ADMIN_PASSWORD=' + secrets.token_urlsafe(16))
"

# Создать .env.production
cat > .env.production << 'EOF'
DATABASE_URL=postgresql://erp_user:ПАРОЛЬ_ОТСЮДА@localhost:5432/erp_prod
ERP_AUTH_SECRET=СЕКРЕТ_ОТСЮДА
ERP_INITIAL_ADMIN_PASSWORD=ПАРОЛЬ_АДМИНИСТРАТОРА_ОТСЮДА
ERP_SERVER_PORT=8000
ENVIRONMENT=production
EOF

# Проверить что приложение запускается
source .env.production
python -m uvicorn app.main:app
# Если зелёные логи без ошибок - OK!
```

---

## 🎯 ЭТАП 2: High Priority (День 2)

### Задача 4: CI/CD Pipeline (2-3 часа)

**Что делать:**
1. Создать `.github/workflows/deploy.yml`
2. Добавить secrets в GitHub
3. Проверить что pipeline работает

**Быстрый способ:**
```bash
# Создать файл
mkdir -p .github/workflows
cat > .github/workflows/deploy.yml << 'EOF'
name: Deploy

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        options: --health-cmd pg_isready --health-interval 10s
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: |
          export DATABASE_URL=postgresql://test:test@localhost/test_db
          pytest -q
EOF

# Запушить в GitHub
git add .github/workflows/deploy.yml
git commit -m "Add GitHub Actions CI/CD"
git push origin main
```

**Проверить:**
- Открыть GitHub Actions tab
- Должно быть зелёная галочка на последнем коммите

---

### Задача 5: Backup процедура (1 час)

**Что делать:**
1. Создать backup script
2. Настроить cron job
3. Проверить что backup работает

**Быстрый способ:**
```bash
# Создать скрипт
cat > tools/backup_postgres.sh << 'EOF'
#!/bin/bash
export PGPASSWORD=$POSTGRES_PASSWORD
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
pg_dump -h localhost -U erp_user erp_prod | gzip > backups/erp_${TIMESTAMP}.sql.gz
echo "Backup создан: backups/erp_${TIMESTAMP}.sql.gz"
EOF

chmod +x tools/backup_postgres.sh

# Добавить в crontab (запускать каждый день в 2 AM)
# 0 2 * * * cd /app && /app/tools/backup_postgres.sh

# Протестировать сейчас
./tools/backup_postgres.sh
ls -lh backups/
```

---

## 🎯 ЭТАП 3: Финальная проверка (День 3)

### Задача 6: Production smoke test (1-2 часа)

**Что проверить:**

```bash
# 1. HTTPS работает
curl -I https://your-domain.com
# Должно быть: HTTP/1.1 200 OK

# 2. API работает
curl https://your-domain.com/health
# Должно быть: {"status":"ok"}

# 3. Админ может войти
curl -X POST https://your-domain.com/api/v1/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your-password"}' \
  -s | python -m json.tool
# Должно быть: {"access_token":"..."}

# 4. E2E тесты проходят
npm run test:e2e
# Должно быть: 5 passed

# 5. Все backend тесты проходят
pytest -q
# Должно быть: 49 passed

# 6. Backup работает
./tools/backup_postgres.sh
ls -lh backups/ | head -1
# Должен быть файл за последние 2 минуты

# 7. Базовая функциональность:
# - Зайти в админ-панель https://your-domain.com
# - Создать клиента
# - Создать заказ
# - Создать продажу
# - Скачать отчёт
```

---

## 📋 Чек-лист для Дня Публикации

### Перед запуском в production

- [ ] HTTPS работает (curl -I https://your-domain.com)
- [ ] PostgreSQL подключена (psql -U erp_user erp_prod)
- [ ] Миграции выполнены (alembic current)
- [ ] `.env.production` заполнен и безопасен
- [ ] Backup работает (./tools/backup_postgres.sh)
- [ ] Все тесты зелёные (pytest -q + npm run test:e2e)
- [ ] GitHub Actions pipeline зелёный
- [ ] Health-check отвечает (curl https://your-domain.com/ready)
- [ ] Админ может войти
- [ ] Админ может создать пользователя
- [ ] Логи видны (docker-compose logs -f)

### В день публикации

- [ ] Создать последний backup
- [ ] Задокументировать URL production
- [ ] Задокументировать пароль администратора (в менеджере паролей)
- [ ] Настроить мониторинг (если используется)
- [ ] Подготовить процедуру rollback
- [ ] Оповестить team что система живая

### После публикации

- [ ] Проверить что приложение отвечает
- [ ] Проверить логи на ошибки
- [ ] Перезагрузить админ в браузере (F5)
- [ ] Создать тестовый заказ
- [ ] Проверить что backup работает через час

---

## 🆘 Что Если Что-то Пошло Не Так?

### "Connection refused" после запуска

```bash
# 1. Проверить что PostgreSQL работает
docker ps | grep postgres

# 2. Проверить DATABASE_URL
echo $DATABASE_URL

# 3. Проверить что БД существует
docker exec erp-postgres psql -U erp_user -l

# 4. Перезапустить контейнер
docker-compose restart postgres
```

### "502 Bad Gateway"

```bash
# 1. Проверить логи приложения
docker-compose logs erp-app | tail -50

# 2. Проверить что приложение запущено
docker ps | grep erp

# 3. Перезагрузить
docker-compose restart erp-app
```

### "SSL certificate error"

```bash
# Проверить сертификат
sudo certbot certificates

# Обновить
sudo certbot renew --dry-run

# Перезагрузить Nginx
sudo systemctl reload nginx
```

---

## 📞 Какие Вопросы Задать Перед Публикацией?

1. **Где будет работать?** (AWS/DigitalOcean/VPS/Kubernetes?)
2. **Какой домен?** (https://erp.example.com?)
3. **Кто будет первым админом?**
4. **Где хранить backups?** (тот же сервер? S3? другой сервер?)
5. **Какой мониторинг нужен?** (логи в ELK? метрики в Prometheus?)
6. **Кто обслуживать?** (DevOps team? внешний провайдер?)

---

## ✅ Готово!

Если вы прошли все этапы - **проект готов к production** 🚀

**Для вопросов смотрите:**
- `PRODUCTION_READINESS_PLAN.md` - полный план
- `RELEASE_AUDIT_FINAL.md` - финальный аудит
- `DEPLOYMENT.md` - подробная инструкция

---

*Последнее обновление: 2026-08-26*
