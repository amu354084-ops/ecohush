from __future__ import annotations

from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.api.auth_dependencies import require_section
from app.models.schema import AppSetting


class SettingResponse(BaseModel):
    key: str
    value: str | None


class SettingUpdateRequest(BaseModel):
    value: str | None = Field(default=None, max_length=1000)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


session_dependency = Depends(get_session)
router = APIRouter(dependencies=[Depends(require_section("settings"))])


@router.get("/", response_model=list[SettingResponse])
async def list_settings(session: AsyncSession = session_dependency) -> list[SettingResponse]:
    result = await session.execute(select(AppSetting))
    rows = result.scalars().all()
    return [SettingResponse(key=row.key, value=row.value) for row in rows]


@router.get("/{key}", response_model=SettingResponse)
async def get_setting(
    key: str = Path(..., min_length=1, max_length=128),
    session: AsyncSession = session_dependency,
) -> SettingResponse:
    setting = await session.scalar(select(AppSetting).where(AppSetting.key == key))
    if setting is None:
        raise HTTPException(status_code=404, detail="Setting not found")
    return SettingResponse(key=setting.key, value=setting.value)


@router.put("/{key}", response_model=SettingResponse)
async def update_setting(
    payload: SettingUpdateRequest,
    key: str = Path(..., min_length=1, max_length=128),
    session: AsyncSession = session_dependency,
) -> SettingResponse:
    setting = await session.scalar(select(AppSetting).where(AppSetting.key == key))
    if setting is None:
        setting = AppSetting(key=key, value=payload.value)
        session.add(setting)
    else:
        setting.value = payload.value
        session.add(setting)
    await session.commit()
    return SettingResponse(key=setting.key, value=setting.value)
