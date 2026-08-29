from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler


logger = logging.getLogger(__name__)

REPORT_HEADERS = {
    "Продажи": ["Продажа №", "Клиент", "Телефон клиента", "Товары", "Сумма", "Оплачено", "Задолженность", "Способ оплаты", "Дата и время"],
    "Состав продаж": ["Продажа №", "Товар №", "Товар", "Количество", "Цена", "Себестоимость", "Скидка сумма", "Скидка %"],
    "Накладные расходы": ["ID", "Категория", "Сумма", "Дата"],
    "Зарплата": ["Сотрудник", "Период", "Вид работы", "Выработка", "Ставка", "Бонус", "Итого"],
    "Штрафы": ["Сотрудник", "Период", "Сумма штрафа", "Комментарий", "Дата"],
    "Общий счет": ["Выручка", "Себестоимость", "Накладные расходы", "Зарплата", "Штрафы", "Зарплата к выплате", "Приходы денег", "Расходы денег", "Общий счет компании", "Прибыль"],
}


def _setting(name: str) -> str | None:
    value = os.getenv(name)
    if value and value.strip():
        return value.strip()
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, separator, candidate = line.partition("=")
        if separator and key.strip() == name:
            return candidate.strip().strip('"').strip("'") or None
    return None


def _cell_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _section_values(title: str, rows: list[dict[str, Any]]) -> list[list[Any]]:
    headers = REPORT_HEADERS.get(title) or (list(rows[0].keys()) if rows else ["Нет данных"])
    return [headers] + [[_cell_value(row.get(header, "")) for header in headers] for row in rows]


def _sync(sections: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    spreadsheet_id = _setting("GOOGLE_SHEETS_SPREADSHEET_ID")
    credentials_path = _setting("GOOGLE_SHEETS_CREDENTIALS_FILE")
    if not spreadsheet_id or not credentials_path:
        return {"status": "disabled", "message": "Google Sheets не настроен"}
    path = Path(credentials_path).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError("Файл учётных данных Google Sheets не найден")
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise RuntimeError("Установите зависимости gspread и google-auth") from exc

    credentials = Credentials.from_service_account_file(
        str(path),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    spreadsheet = gspread.authorize(credentials).open_by_key(spreadsheet_id)
    updated: list[str] = []
    for title, rows in sections.items():
        try:
            worksheet = spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=title, rows=max(len(rows) + 1, 100), cols=20)
        values = _section_values(title, rows)
        clear_to_row = max(worksheet.row_count, len(values), 1)
        worksheet.batch_clear([f"A1:ZZ{clear_to_row}"])
        worksheet.update(values, "A1")
        updated.append(title)
    return {"status": "ok", "updated_sections": updated}


async def sync_report_sections(sections: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Synchronize report tabs without blocking the FastAPI event loop."""
    try:
        return await asyncio.to_thread(_sync, sections)
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


async def sync_reports_from_database() -> dict[str, Any]:
    """Build the current report from a fresh DB session and synchronize it."""
    from app.api.reports_api import build_report_sections
    from app.db import async_session

    try:
        async with async_session() as session:
            sections = await build_report_sections(session)
        result = await sync_report_sections(sections)
        if result.get("status") == "error":
            logger.error("Google Sheets sync failed: %s", result.get("message"))
        return result
    except Exception:
        logger.exception("Google Sheets report job failed")
        return {"status": "error", "message": "Ошибка фоновой синхронизации Google Sheets"}


def schedule_google_sheets(scheduler: AsyncIOScheduler) -> None:
    """Register periodic sync only when Google Sheets is fully configured."""
    if not _setting("GOOGLE_SHEETS_SPREADSHEET_ID") or not _setting("GOOGLE_SHEETS_CREDENTIALS_FILE"):
        logger.info("Google Sheets sync is disabled: configuration is incomplete")
        return
    minutes = max(1, int(_setting("GOOGLE_SHEETS_SYNC_MINUTES") or "720"))
    scheduler.add_job(
        sync_reports_from_database,
        "interval",
        minutes=minutes,
        id="google-sheets-reports-sync",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
        coalesce=True,
        max_instances=1,
    )
    logger.info("Google Sheets report sync scheduled every %s minutes", minutes)
