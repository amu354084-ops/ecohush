from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import require_section
from app.db import async_session
from app.services.dashboard import build_dashboard_summary


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session


session_dependency = Depends(get_session)
router = APIRouter(dependencies=[Depends(require_section("dashboard"))])


@router.get("/summary")
async def dashboard_summary(session: AsyncSession = session_dependency) -> dict:
    return await build_dashboard_summary(session)
