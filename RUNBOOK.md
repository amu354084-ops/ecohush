# Runbook: ERP Local

## Диагностика

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 web
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=200 db
curl -i http://127.0.0.1:1833/health
curl -i http://127.0.0.1:1833/ready
```

`/health` проверяет процесс и БД. `/ready` возвращает HTTP 503, если БД недоступна.

## Перезапуск приложения

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml restart web
```

## Backup

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec web sh /app/scripts/backup_postgres.sh
ls -lh backups/
```

Храните копии вне VPS. Локальная ротация удаляет файлы старше 7 дней. Наличие backup само по себе не считается проверенным: нужен периодический restore-тест.

## Восстановление PostgreSQL

Остановите приложение, чтобы не было записи во время восстановления:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml stop web
zcat backups/postgres_erp_local_YYYYMMDD_HHMMSS.sql.gz | docker compose --env-file .env.production -f docker-compose.prod.yml exec -T db psql -U erp_user -d erp_local
# При восстановлении полного дампа сначала очистите целевую базу по утвержденной процедуре.
docker compose --env-file .env.production -f docker-compose.prod.yml start web
curl -fsS http://127.0.0.1:1833/ready
```

Не выполняйте restore в production без подтверждения окна обслуживания и сохранения текущего backup.

## Rollback приложения

```bash
cd /opt/erp_local
git log --oneline -5
git checkout KNOWN_GOOD_COMMIT
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
curl -fsS http://127.0.0.1:1833/ready
```

Миграции базы откатывайте только после проверки совместимости кода и схемы. Для необратимых изменений сначала сделайте backup.

## Безопасность инцидента

1. Закройте внешний доступ к приложению firewall-правилом.
2. Сохраните логи и текущий backup.
3. Ротируйте `ERP_AUTH_SECRET`, пароль PostgreSQL, S3-ключи и SSH-ключ, если они могли раскрыться.
4. Проверьте активные токены и пользователей.
5. Зафиксируйте причину и выполненные действия.

## Перед публичным запуском

- [ ] Домен указывает на VPS
- [ ] TLS через Let's Encrypt проверен снаружи
- [ ] Начальный пароль заменён на уникальный
- [ ] `CHANGE_ME` отсутствует в production env
- [ ] Backup загружен в S3
- [ ] Restore-тест выполнен
- [ ] `/health` и `/ready` отвечают корректно
- [ ] GitHub Actions прошёл тесты и deploy
- [ ] Rollback проверен на staging/копии
