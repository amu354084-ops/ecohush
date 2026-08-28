# Ежедневная копия базы на ПК

Сервер автоматически создает SQLite-файл `backup_YYYYMMDD_HHMMSS.db` каждый день в `BACKUP_DIR` (по умолчанию `backups`). Время задается переменными `BACKUP_TIMEZONE`, `BACKUP_HOUR` и `BACKUP_MINUTE`. Скачивание доступно только роли `ADMIN` по адресу `/api/v1/admin/backup/database-download`.

## Windows-клиент

Скрипт `tools/download_daily_backup.ps1` использует учетную запись администратора и сохраняет каждую успешную загрузку на локальный диск.

1. Создайте отдельную учетную запись с ролью `ADMIN`.
2. Один раз задайте переменные среды пользователя:

```powershell
[Environment]::SetEnvironmentVariable("ERP_SERVER_URL", "https://erp.example.com", "User")
[Environment]::SetEnvironmentVariable("ERP_BACKUP_USERNAME", "backup-admin", "User")
[Environment]::SetEnvironmentVariable("ERP_BACKUP_PASSWORD", "пароль", "User")
[Environment]::SetEnvironmentVariable("ERP_BACKUP_DIRECTORY", "D:\ERP-Backups", "User")
```

3. Проверьте вручную:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\tools\download_daily_backup.ps1
```

4. Зарегистрируйте ежедневный запуск автоматически, например в 03:15:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\tools\install_daily_backup_task.ps1 -RunAt 03:15
```

Либо в Планировщике заданий Windows задайте действие:

```text
powershell.exe -ExecutionPolicy Bypass -File C:\Users\Mi\ERP_Local\tools\download_daily_backup.ps1
```

Скрипт сначала пишет во временный файл, проверяет ненулевой размер и только затем перемещает его в папку назначения. Старше 30 дней локальные `.db`-копии удаляются.
