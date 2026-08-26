from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.auth_dependencies import require_roles
from app.services.backup import create_database_backup, create_local_backup

router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_roles("ADMIN"))])


@router.post("/create")
def create_backup(_: object = Depends(require_roles("ADMIN"))) -> dict[str, str]:
    return create_local_backup()


@admin_router.post("/backup")
def create_admin_backup() -> dict[str, str]:
    return create_local_backup()


@admin_router.get("/backup/download")
def download_admin_backup() -> FileResponse:
    result = create_local_backup()
    return FileResponse(
        result["path"],
        media_type="application/zip",
        filename=f"Резервная_копия_ERP_{result['created_at']}.zip",
    )


@admin_router.get("/backup/database-download")
def download_database_backup() -> FileResponse:
    result = create_database_backup()
    media_type = "application/x-sqlite3" if result["filename"].endswith(".db") else "application/octet-stream"
    return FileResponse(result["path"], media_type=media_type, filename=result["filename"])
