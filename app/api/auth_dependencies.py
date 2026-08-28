from __future__ import annotations

import hashlib
import json
from typing import AsyncGenerator

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.schema import User
from app.services.auth import decode_token

SECTION_DEFAULT_ROLES = {
    "dashboard": {"ADMIN", "TECHNOLOGIST", "AGENT", "WORKER"}, "orders": {"ADMIN", "COURIER"},
    "clients": {"ADMIN", "COURIER"}, "warehouse": {"ADMIN", "TECHNOLOGIST", "AGENT"},
    "sales": {"ADMIN", "TECHNOLOGIST", "AGENT", "WORKER"}, "production": {"ADMIN", "TECHNOLOGIST", "AGENT", "WORKER"},
    "shipments": {"ADMIN", "TECHNOLOGIST", "AGENT", "WORKER"}, "finance": {"ADMIN", "TECHNOLOGIST", "AGENT", "WORKER"},
    "reports": {"ADMIN"}, "formula": {"ADMIN", "TECHNOLOGIST", "AGENT", "WORKER"}, "debts": {"ADMIN"},
    "users": {"ADMIN"}, "settings": {"ADMIN"}, "backup": {"ADMIN"},
}


def user_permissions(user: User) -> set[str]:
    if user.role == "ADMIN":
        return set(SECTION_DEFAULT_ROLES)
    permissions_value = getattr(user, "permissions", None)
    if permissions_value:
        try:
            permissions = json.loads(permissions_value)
            if isinstance(permissions, list):
                return {item for item in permissions if item in SECTION_DEFAULT_ROLES}
        except (TypeError, ValueError):
            pass
    return {section for section, roles in SECTION_DEFAULT_ROLES.items() if user.role in roles}


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    decoded = decode_token(authorization[7:])
    user = None
    if decoded:
        try:
            user = await session.get(User, decoded["sub"])
        except OperationalError as exc:
            if "users.permissions" not in str(exc):
                raise
            await session.rollback()
            await session.execute(text("ALTER TABLE users ADD COLUMN permissions TEXT"))
            await session.commit()
            user = await session.get(User, decoded["sub"])
    if (
        user is None
        or not user.is_active
        or user.username != decoded.get("username")
        or user.role != decoded.get("role")
        or decoded.get("password_marker") != hashlib.sha256(user.password_hash.encode()).hexdigest()
    ):
        raise HTTPException(status_code=401, detail="Недействительный токен")
    if user.must_change_password and request.url.path not in {"/api/v1/me", "/api/v1/users/me/password"}:
        raise HTTPException(status_code=403, detail="Сначала смените обязательный пароль")
    return user


def require_roles(*roles: str):
    async def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Недостаточно прав")
        return user

    return dependency


def require_non_courier():
    async def dependency(user: User = Depends(current_user)) -> User:
        if "dashboard" not in user_permissions(user):
            raise HTTPException(status_code=403, detail="Курьеру доступен только каталог, клиенты и свои заказы")
        return user

    return dependency


def require_section(section: str):
    async def dependency(user: User = Depends(current_user)) -> User:
        if section not in user_permissions(user):
            raise HTTPException(status_code=403, detail="Раздел недоступен для этого сотрудника")
        return user

    return dependency
