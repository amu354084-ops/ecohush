from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from app.services.backup import _setting, create_local_backup


logger = logging.getLogger(__name__)
POLL_TIMEOUT = 20


def _api_request(token: str, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = urllib.parse.urlencode(payload or {}).encode() if payload else None
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"} if data else {},
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(request, timeout=POLL_TIMEOUT + 10) as response:  # noqa: S310
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result.get("description") or "Telegram API error")
    return result


def _keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [[
            {"text": "Создать бэкап", "callback_data": "backup"},
            {"text": "Показать отчёт", "callback_data": "report"},
        ]]
    }


def _send_message(token: str, chat_id: str, text: str) -> None:
    _api_request(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": json.dumps(_keyboard(), ensure_ascii=False),
    })


def _send_document(token: str, chat_id: str, archive_path: Path) -> None:
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
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Telegram document upload failed: HTTP {response.status}")


async def _report_text() -> str:
    from app.api.reports_api import build_report_sections
    from app.db import async_session

    async with async_session() as session:
        sections = await build_report_sections(session)
    summary = sections["Общий счет"][0]
    return (
        "Отчёт Eco Khush\n"
        f"Выручка: {summary['Выручка']}\n"
        f"Себестоимость: {summary['Себестоимость']}\n"
        f"Расходы: {summary['Накладные расходы']}\n"
        f"Прибыль: {summary['Прибыль']}\n"
        f"Баланс компании: {summary['Общий счет компании']}"
    )


async def _handle_update(token: str, allowed_chat_id: str, update: dict[str, Any]) -> None:
    message = update.get("message") or {}
    callback = update.get("callback_query") or {}
    chat = message.get("chat") or (callback.get("message") or {}).get("chat") or {}
    chat_id = str(chat.get("id", ""))
    if not chat_id or chat_id != allowed_chat_id:
        return
    action = callback.get("data")
    text = str(message.get("text") or "")
    if text in {"/start", "/menu"}:
        await asyncio.to_thread(_send_message, token, chat_id, "Панель Eco Khush готова. Выберите действие:")
    elif action == "backup":
        result = await asyncio.to_thread(create_local_backup, False)
        await asyncio.to_thread(_send_document, token, chat_id, Path(result["path"]))
    elif action == "report":
        await asyncio.to_thread(_send_message, token, chat_id, await _report_text())
    if callback.get("id"):
        try:
            await asyncio.to_thread(_api_request, token, "answerCallbackQuery", {"callback_query_id": callback["id"]})
        except Exception:
            logger.info("Telegram callback expired or was already acknowledged")


async def run_telegram_bot(stop_event: asyncio.Event) -> None:
    token = _setting("TELEGRAM_BOT_TOKEN")
    chat_id = _setting("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.info("Telegram bot is disabled: configuration is incomplete")
        return
    offset = 0
    logger.info("Telegram bot polling started")
    while not stop_event.is_set():
        try:
            result = await asyncio.to_thread(_api_request, token, "getUpdates", {
                "offset": offset,
                "timeout": POLL_TIMEOUT,
                "allowed_updates": json.dumps(["message", "callback_query"]),
            })
            for update in result.get("result", []):
                offset = max(offset, int(update["update_id"]) + 1)
                try:
                    await _handle_update(token, chat_id, update)
                except Exception:
                    logger.exception("Telegram bot update failed")
        except Exception:
            logger.exception("Telegram bot polling failed; retrying")
            await asyncio.sleep(5)
