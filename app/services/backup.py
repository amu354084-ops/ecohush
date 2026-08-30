from __future__ import annotations

import os
import hashlib
import json
import sqlite3
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.excel_export import export_database_to_excel

BACKUP_RETENTION_DAYS = 30


def _setting(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, separator, candidate = line.partition("=")
        if separator and key.strip() == name:
            return candidate.strip().strip('"').strip("'") or None
    return None


def backup_directory() -> Path:
    configured = _setting("BACKUP_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "backups"


def database_path() -> Path:
    from app.db import DATABASE_URL

    if DATABASE_URL.startswith("sqlite+aiosqlite:///"):
        return Path(DATABASE_URL.removeprefix("sqlite+aiosqlite:///"))
    raise RuntimeError("Local ZIP backup is supported only for SQLite")


def cleanup_old_backups(directory: Path | None = None) -> int:
    target = directory or backup_directory()
    threshold = datetime.now() - timedelta(days=BACKUP_RETENTION_DAYS)
    removed = 0
    for archive in target.glob("backup_*.zip"):
        if datetime.fromtimestamp(archive.stat().st_mtime) < threshold:
            archive.unlink()
            removed += 1
    for database in target.glob("backup_*.db"):
        if datetime.fromtimestamp(database.stat().st_mtime) < threshold:
            database.unlink()
            removed += 1
    return removed


def create_database_backup() -> dict[str, Any]:
    target_directory = backup_directory()
    target_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    from app.db import DATABASE_URL

    if DATABASE_URL.startswith(("postgresql+asyncpg://", "postgresql://")):
        target = target_directory / f"backup_{timestamp}.dump"
        dump_url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
        parsed = urlsplit(dump_url)
        if not parsed.hostname or not parsed.username or parsed.password is None:
            raise RuntimeError("DATABASE_URL для PostgreSQL должен содержать host, user и password")

        host = parsed.hostname
        port = parsed.port or 5432
        database = parsed.path.lstrip("/")
        password = parsed.password
        username = parsed.username
        netloc = f"{username}:{password}@{host}:{port}/{database}"
        pg_url = f"postgresql://{netloc}"

        escaped_password = password.replace("\\", "\\\\").replace(":", "\\:")
        pgpass_line = f"{host}:{port}:{database}:{username}:{escaped_password}\n"
        pgpass_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".pgpass", delete=False) as pgpass:
                pgpass.write(pgpass_line)
                pgpass_path = Path(pgpass.name)
            pgpass_path.chmod(0o600)
            subprocess.run(
                ["pg_dump", "--format=custom", "--file", str(target), pg_url],
                check=True,
                capture_output=True,
                text=True,
                env={**os.environ, "PGPASSFILE": str(pgpass_path)},
            )
        except FileNotFoundError as exc:
            raise RuntimeError("pg_dump не найден. Установите postgresql-client на сервере.") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"Не удалось создать резервную копию PostgreSQL: {exc.stderr.strip()}") from exc
        finally:
            if pgpass_path and pgpass_path.exists():
                pgpass_path.unlink()
        return {"path": str(target), "filename": target.name, "created_at": timestamp}

    source = database_path()
    if not source.exists():
        raise FileNotFoundError(f"Database file not found: {source}")
    target = target_directory / f"backup_{timestamp}.db"
    temporary = target.with_suffix(".db.tmp")
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
    finally:
        source_connection.close()
        target_connection.close()
    try:
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"path": str(target), "filename": target.name, "created_at": timestamp}


def send_backup_to_telegram(archive_path: Path) -> bool:
    token = _setting("TELEGRAM_BOT_TOKEN")
    chat_id = _setting("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    boundary = "----ERPBackupBoundary"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=chat_id\r\n\r\n{chat_id}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=document; filename={archive_path.name}\r\n"
        "Content-Type: application/zip\r\n\r\n"
    ).encode() + archive_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def create_local_backup(notify_telegram: bool = True) -> dict[str, Any]:
    from app.db import DATABASE_URL

    target_directory = backup_directory()
    target_directory.mkdir(parents=True, exist_ok=True)
    if DATABASE_URL.startswith(("postgresql+asyncpg://", "postgresql://")):
        database_backup = create_database_backup()
        snapshot_path = Path(database_backup["path"])
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        archive_path = target_directory / f"backup_{timestamp}.zip"
        database_hash = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        manifest = {
            "название": "Резервная копия ERP",
            "создано": datetime.now().isoformat(timespec="seconds"),
            "база_данных": snapshot_path.name,
            "sha256_базы": database_hash,
            "excel_файл": None,
            "назначение": "Резервная копия PostgreSQL в формате pg_dump.",
        }
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot_path, arcname=snapshot_path.name)
            archive.writestr("описание_резервной_копии.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        removed = cleanup_old_backups(target_directory)
        return {
            "path": str(archive_path),
            "filename": archive_path.name,
            "excel_path": None,
            "created_at": timestamp,
            "telegram_sent": send_backup_to_telegram(archive_path) if notify_telegram else False,
            "removed_old": removed,
            "database_path": str(snapshot_path),
            "database_filename": snapshot_path.name,
            "database_sha256": database_hash,
            "message": "Резервная копия PostgreSQL создана в формате pg_dump.",
        }

    source = database_path()
    if not source.exists():
        raise FileNotFoundError(f"Database file not found: {source}")
    try:
        database_backup = create_database_backup()
    except sqlite3.DatabaseError:
        database_backup = None
    excel_directory = target_directory / f"excel_{datetime.now():%Y_%m_%d}"
    excel_path: Path | None = None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    archive_path = target_directory / f"backup_{timestamp}.zip"
    # Use the SQLite snapshot for both files so the archive is internally consistent.
    snapshot_path = Path(database_backup["path"]) if database_backup else source
    try:
        excel_path = export_database_to_excel(snapshot_path, excel_directory)
    except (OSError, ValueError, sqlite3.DatabaseError):
        pass
    database_hash = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    manifest = {
        "название": "Резервная копия ERP",
        "создано": datetime.now().isoformat(timespec="seconds"),
        "база_данных": snapshot_path.name,
        "sha256_базы": database_hash,
        "excel_файл": excel_path.name if excel_path else None,
        "назначение": "База данных является точной копией. Excel предназначен для просмотра и анализа.",
    }
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(snapshot_path, arcname=snapshot_path.name)
        if excel_path:
            archive.write(excel_path, arcname=excel_path.name)
        archive.writestr("описание_резервной_копии.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    removed = cleanup_old_backups(target_directory)
    return {
        "path": str(archive_path),
        "filename": archive_path.name,
        "excel_path": str(excel_path) if excel_path else None,
        "created_at": timestamp,
        "telegram_sent": send_backup_to_telegram(archive_path) if notify_telegram else False,
        "removed_old": removed,
        "database_path": database_backup["path"] if database_backup else None,
        "database_filename": database_backup["filename"] if database_backup else None,
        "database_sha256": database_hash,
        "message": "Резервная копия создана. База данных сохранена без изменений, Excel добавлен для просмотра.",
    }


def run_db_backup() -> dict[str, Any]:
    return create_local_backup()


def schedule_backups() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=_setting("BACKUP_TIMEZONE") or "Asia/Dushanbe")
    scheduler.add_job(
        create_local_backup,
        "cron",
        hour=int(_setting("BACKUP_HOUR") or "23"),
        minute=int(_setting("BACKUP_MINUTE") or "0"),
        id="daily-local-backup",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler
