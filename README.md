# ERP Local Enterprise

Web/SaaS ERP/MRP для производства, склада, продаж и финансовой аналитики. Основной production-сценарий запускается на Linux/VPS через FastAPI, Docker и PostgreSQL.

## Структура

- `app/main.py` — точка входа сервера.
- `app/models/schema.py` — SQLAlchemy модели данных.
- `app/services/inventory.py` — FIFO-логика и создание партий.
- `app/services/production.py` — производство, обратный возврат и расходы.
- `app/services/backup.py` — планировщик резервного копирования.
- `app/api/production_api.py` — API маршруты производства и возвратов.
- `installer.iss` — шаблон Inno Setup для сборки одного инсталлятора.

## Запуск

1. Установите виртуальное окружение Python 3.11+.
2. `pip install -r requirements.txt` (или `pip install .`).
   - Это установит и зависимости для тестов (`httpx2` для FastAPI `TestClient`).
3. Скопируйте `.env.production.example` в `.env` и задайте секреты, IP сервера и `DATABASE_URL`.
4. Для локального запуска используйте `python -m app.main`.

## Деплой на Linux/VPS

1. Установите Docker Engine и Docker Compose Plugin.
2. Создайте production-конфигурацию: `cp .env.production.example .env`.
3. Замените `YOUR_SERVER_IP`, `ERP_AUTH_SECRET`, `ERP_INITIAL_ADMIN_PASSWORD`, `POSTGRES_PASSWORD` и пароль в `DATABASE_URL`.
4. Запустите: `docker compose up -d --build`.
5. Проверьте готовность: `curl http://SERVER_IP:1833/health`.

Ответ health-check: `{"status":"ok"}`. PostgreSQL хранится в Docker volume, резервные копии монтируются в `./backups`.

Для публичного production-доступа используйте firewall и reverse proxy с HTTPS. Не публикуйте порт PostgreSQL наружу.

## Сборка

- `pytest -q`
- `docker compose config`
