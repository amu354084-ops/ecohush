from __future__ import annotations

import json
import time
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import exists, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import SECTION_DEFAULT_ROLES, current_user, get_session, require_roles, require_section, user_permissions
from app.models.schema import Counterparty, Item, ItemType, Order, OrderItem, OrderPaymentType, OrderStatus, Sale, User
from app.services.auth import create_token, hash_password, verify_password
from app.services.invoice import invoice_html
from app.services.orders import accept_order, create_order, reject_order, transition_order

router = APIRouter()
_login_failures: dict[str, list[float]] = {}
LOGIN_WINDOW_SECONDS = 60
LOGIN_MAX_FAILURES = 10


class LoginRequest(BaseModel):
    username: str
    password: str


class OrderItemRequest(BaseModel):
    item_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    price: Decimal | None = Field(default=None, ge=0)
    discount_percent: Decimal | None = Field(default=None, ge=0, le=100)
    discount: Decimal | None = Field(default=None, ge=0)


class OrderCreateRequest(BaseModel):
    client_id: int = Field(gt=0)
    items: list[OrderItemRequest] = Field(min_length=1)


class AcceptRequest(BaseModel):
    discount_amount: Decimal = Field(default=Decimal(0), ge=0)


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1)


class TransitionRequest(BaseModel):
    status: OrderStatus
    payment_type: OrderPaymentType | None = None
    paid_amount: Decimal = Field(default=Decimal(0), ge=0)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8)
    full_name: str | None = None
    role: str = Field(default="COURIER", pattern="^(ADMIN|COURIER|TECHNOLOGIST|AGENT|WORKER)$")
    can_change_status: bool = False
    permissions: list[str] | None = None


class PasswordResetRequest(BaseModel):
    password: str = Field(min_length=8)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class UserStateRequest(BaseModel):
    is_active: bool


class UserPermissionsRequest(BaseModel):
    permissions: list[str] = Field(default_factory=list)


@router.post("/login")
async def login(request: LoginRequest, http_request: Request, session: AsyncSession = Depends(get_session)):
    now = time.monotonic()
    client_key = f"{http_request.client.host if http_request.client else 'unknown'}:{request.username.casefold()}"
    failures = [stamp for stamp in _login_failures.get(client_key, []) if now - stamp < LOGIN_WINDOW_SECONDS]
    if len(failures) >= LOGIN_MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Слишком много попыток входа. Повторите через минуту")
    user = (
        await session.execute(
            select(User.id, User.username, User.password_hash, User.role, User.is_active, User.must_change_password)
            .where(User.username == request.username)
        )
    ).one_or_none()
    if user is None or not user.is_active or not verify_password(request.password, user.password_hash):
        failures.append(now)
        _login_failures[client_key] = failures
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    _login_failures.pop(client_key, None)
    return {
        "access_token": create_token(user),
        "token_type": "bearer",
        "role": user.role,
        "must_change_password": user.must_change_password,
        "permissions": sorted(user_permissions(user)),
    }


@router.post("/users/me/password")
async def change_own_password(
    data: PasswordChangeRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Текущий пароль указан неверно")
    user.password_hash = hash_password(data.new_password)
    user.must_change_password = False
    await session.commit()
    return {"message": "Пароль изменён"}


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "permissions": sorted(user_permissions(user)),
    }


@router.get("/orders/catalog")
async def order_catalog(_: User = Depends(require_section("orders")), session: AsyncSession = Depends(get_session)):
    items = (await session.execute(select(Item).where(Item.type == ItemType.FINAL).order_by(Item.name))).scalars().all()
    return [{"id": item.id, "name": item.name, "code": item.code, "unit": item.unit, "type_code": item.type.value, "price": str(item.price or 0)} for item in items]


@router.get("/users")
async def list_users(_: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    users = (await session.execute(select(User).order_by(User.username))).scalars().all()
    return [{"id": user.id, "username": user.username, "full_name": user.full_name, "role": user.role, "can_change_status": user.can_change_status, "is_active": user.is_active, "permissions": sorted(user_permissions(user))} for user in users]


@router.post("/users")
async def create_user(data: UserCreateRequest, _: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    if await session.scalar(select(User).where(User.username == data.username)) is not None:
        raise HTTPException(status_code=409, detail="Логин уже занят")
    selected_permissions = data.permissions
    if selected_permissions is None:
        selected_permissions = [section for section, roles in SECTION_DEFAULT_ROLES.items() if data.role in roles]
    user = User(
        username=data.username, password_hash=hash_password(data.password),
        full_name=data.full_name, role=data.role,
        can_change_status=data.can_change_status if data.role == "COURIER" else False,
        permissions=json.dumps(sorted({permission for permission in selected_permissions if permission in SECTION_DEFAULT_ROLES}), ensure_ascii=True),
    )
    session.add(user)
    await session.commit()
    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/debts")
async def debt_history(q: str | None = None, _: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    outstanding_debt = exists(
        select(Sale.id).where(
            Sale.counterparty_id == Order.client_id,
            Sale.debt_amount > 0,
        )
    )
    query = select(Order).options(selectinload(Order.client), selectinload(Order.items).selectinload(OrderItem.item)).where(
        Order.status == OrderStatus.DELIVERED,
        outstanding_debt,
    ).order_by(Order.delivered_at.desc(), Order.id.desc())
    if q and q.strip():
        search = f"%{q.strip()}%"
        query = query.where(Order.client.has((Counterparty.name.ilike(search)) | (Counterparty.phone.ilike(search))))
    orders = (await session.execute(query)).scalars().all()
    return [{
        "order_id": order.id,
        "invoice_number": order.invoice_number,
        "client_name": order.client.name if order.client else "",
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "total": str(sum((item.quantity * item.price - (item.discount or 0) for item in order.items), Decimal(0)) - (order.discount_amount or 0)),
        "items": [{"name": item.item.name, "quantity": str(item.quantity), "price": str(item.price), "discount": str(item.discount or 0)} for item in order.items],
    } for order in orders]


@router.post("/users/{user_id}/password")
async def reset_password(user_id: int, data: PasswordResetRequest, _: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.password_hash = hash_password(data.password)
    user.must_change_password = True
    await session.commit()
    return {"id": user.id, "message": "Пароль сброшен"}


@router.patch("/users/{user_id}/state")
async def change_user_state(user_id: int, data: UserStateRequest, _: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.is_active = data.is_active
    await session.commit()
    return {"id": user.id, "is_active": user.is_active}


@router.patch("/users/{user_id}/permissions")
async def change_user_permissions(
    user_id: int,
    data: UserPermissionsRequest,
    admin: User = Depends(require_roles("ADMIN")),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    valid = {permission for permission in data.permissions if permission in user_permissions(admin)}
    if user.role == "ADMIN" and user.id == admin.id:
        valid = user_permissions(user)
    user.permissions = json.dumps(sorted(valid), ensure_ascii=True)
    await session.commit()
    return {"id": user.id, "permissions": sorted(valid)}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, admin: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Нельзя удалить свою учётную запись")
    user.is_active = False
    user.permissions = json.dumps([], ensure_ascii=True)
    await session.commit()
    return {"id": user.id, "is_active": False, "message": "Сотрудник архивирован"}


@router.post("/orders")
async def create(data: OrderCreateRequest, user: User = Depends(require_section("orders")), session: AsyncSession = Depends(get_session)):
    order = await create_order(session, user.id, data.client_id, [item.model_dump() for item in data.items])
    await session.commit()
    return {"id": order.id, "status": order.status}


@router.get("/orders")
async def list_orders(
    status: OrderStatus | None = None,
    limit: int = 10,
    offset: int = 0,
    user: User = Depends(require_section("orders")),
    session: AsyncSession = Depends(get_session),
):
    query = select(Order).options(
        selectinload(Order.client),
        selectinload(Order.courier),
        selectinload(Order.items).selectinload(OrderItem.item),
    ).order_by(Order.created_at.desc(), Order.id.desc())
    if user.role == "COURIER":
        query = query.where(Order.courier_id == user.id)
    if status is not None:
        query = query.where(Order.status == status)
    result = await session.execute(query.limit(max(1, min(limit, 100))).offset(max(0, offset)))
    return [
        {
            "id": order.id,
            "invoice_number": order.invoice_number,
            "client_name": order.client.name if order.client else "",
            "courier_name": (
                order.courier.full_name or order.courier.username
                if order.courier else ""
            ),
            "items": [
                {
                    "name": item.item.name,
                    "quantity": str(item.quantity),
                    "unit": item.item.unit,
                    "price": str(item.price),
                    "discount": str(item.discount or 0),
                }
                for item in order.items
            ],
            "status": order.status.value if hasattr(order.status, "value") else order.status,
            "rejection_reason": order.rejection_reason,
            "discount_amount": str(order.discount_amount or 0),
            "created_at": order.created_at.isoformat() if order.created_at else None,
        }
        for order in result.scalars().all()
    ]


@router.get("/orders/{order_id}/invoice", response_class=HTMLResponse)
async def order_invoice(
    order_id: int,
    user: User = Depends(require_section("orders")),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    query = select(Order).options(
        selectinload(Order.client), selectinload(Order.courier),
        selectinload(Order.items).selectinload(OrderItem.item),
    ).where(Order.id == order_id)
    order = await session.scalar(query)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if user.role == "COURIER" and order.courier_id != user.id:
        raise HTTPException(status_code=403, detail="Доступ только к своим заказам")
    if order.status not in (OrderStatus.ACCEPTED, OrderStatus.IN_TRANSIT, OrderStatus.DELIVERED):
        raise HTTPException(status_code=404, detail="Накладная доступна только для принятых и доставленных заказов")
    return HTMLResponse(invoice_html(order))


@router.post("/orders/{order_id}/accept")
async def accept(order_id: int, data: AcceptRequest, _: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    order = await accept_order(session, order_id, data.discount_amount)
    await session.commit()
    return {"id": order.id, "status": order.status, "invoice_number": order.invoice_number}


@router.post("/orders/{order_id}/reject")
async def reject(order_id: int, data: RejectRequest, _: User = Depends(require_roles("ADMIN")), session: AsyncSession = Depends(get_session)):
    order = await reject_order(session, order_id, data.reason)
    await session.commit()
    return {"id": order.id, "status": order.status, "rejection_reason": order.rejection_reason}


@router.post("/orders/{order_id}/transition")
async def transition(order_id: int, data: TransitionRequest, user: User = Depends(require_section("orders")), session: AsyncSession = Depends(get_session)):
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if user.role == "COURIER" and order.courier_id != user.id:
        raise HTTPException(status_code=403, detail="Доступ только к своим заказам")
    order = await transition_order(
        session, order_id, data.status, data.payment_type, actor=user, paid_amount=data.paid_amount
    )
    await session.commit()
    return {"id": order.id, "status": order.status, "payment_type": order.payment_type}


@router.post("/orders/{order_id}/deliver")
async def deliver(order_id: int, data: TransitionRequest, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if data.payment_type is None:
        raise HTTPException(status_code=400, detail="Выберите тип оплаты")
    if user.role == "COURIER" and not user.can_change_status:
        raise HTTPException(status_code=403, detail="Курьеру запрещено подтверждать доставку")
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if user.role == "COURIER" and order.courier_id != user.id:
        raise HTTPException(status_code=403, detail="Доступ только к своим заказам")
    order = await transition_order(
        session, order_id, OrderStatus.DELIVERED, data.payment_type, actor=user, paid_amount=data.paid_amount
    )
    await session.commit()
    return {"id": order.id, "status": order.status, "payment_type": order.payment_type}
