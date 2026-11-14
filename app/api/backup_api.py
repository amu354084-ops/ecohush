from __future__ import annotations

import logging
import sqlite3
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.auth_dependencies import require_roles
from app.services.backup import create_database_backup, create_local_backup

logger = logging.getLogger(__name__)

router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_roles("ADMIN"))])


def _run_backup(action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run a backup and turn failures into a readable message instead of a bare HTTP 500."""
    try:
        return action()
    except (RuntimeError, OSError, sqlite3.Error) as exc:
        logger.exception("Backup failed")
        raise HTTPException(status_code=500, detail=f"Не удалось создать резервную копию: {exc}") from exc


@router.post("/create")
def create_backup(_: object = Depends(require_roles("ADMIN"))) -> dict[str, str]:
    return _run_backup(create_local_backup)


@admin_router.post("/backup")
def create_admin_backup() -> dict[str, str]:
    return _run_backup(create_local_backup)


@admin_router.get("/backup/download")
def download_admin_backup() -> FileResponse:
    result = _run_backup(create_local_backup)
    return FileResponse(
        result["path"],
        media_type="application/zip",
        filename=f"Резервная_копия_ERP_{result['created_at']}.zip",
    )


@admin_router.get("/backup/database-download")
def download_database_backup() -> FileResponse:
    result = _run_backup(create_database_backup)
    media_type = "application/x-sqlite3" if result["filename"].endswith(".db") else "application/octet-stream"
    return FileResponse(result["path"], media_type=media_type, filename=result["filename"])
