from __future__ import annotations

from datetime import date, datetime, time, timezone

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
async def dashboard_summary(
    date_from: date | None = None,
    date_to: date | None = None,
    session: AsyncSession = session_dependency,
) -> dict:
    tz = get_app_timezone()
    start = datetime.combine(date_from, time.min, tzinfo=tz) if date_from else None
    end = datetime.combine(date_to, time.max, tzinfo=tz) if date_to else None
    return await build_dashboard_summary(session, start, end)
