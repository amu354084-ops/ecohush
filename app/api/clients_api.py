from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth_dependencies import require_roles, require_section, user_permissions
from app.db import async_session
from app.models.schema import User
from app.models.schema import AuditEvent, CashTransaction, Counterparty, Item, ManualDebt, PaymentMethod, Sale, SaleItem
from app.services.localization import display_label
from app.services.sales import repay_client_debt
from app.services.timezone import get_app_timezone


class ClientCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=64)


class ClientUpdateRequest(ClientCreateRequest):
    pass


class ClientResponse(BaseModel):
    id: int
    name: str
    phone: str | None
    current_debt: str


class ClientSaleHistoryResponse(BaseModel):
    id: int
    created_at: str
    total_amount: str
    paid_amount: str
    debt_amount: str
    items: str


class ClientPaymentHistoryResponse(BaseModel):
    id: int
    created_at: str
    amount: str
    payment_method: str
    description: str


class ClientHistoryResponse(BaseModel):
    client: ClientResponse
    sales: list[ClientSaleHistoryResponse]
    payments: list[ClientPaymentHistoryResponse]
    sales_total: str
    paid_total: str


class ClientPaymentCreateRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    payment_method: PaymentMethod = PaymentMethod.CASH
    description: str = Field(default="Погашение долга", max_length=500)


class ClientPaymentResponse(BaseModel):
    payment_id: int
    client_id: int
    amount: str
    remaining_debt: str
    allocations: list[dict[str, str | int]]


class ManualDebtRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    description: str = Field(default="", max_length=500)


class ManualDebtCreateRequest(ManualDebtRequest):
    client_id: int = Field(gt=0)


class ManualDebtResponse(BaseModel):
    id: int
    client_id: int
    amount: str
    description: str
    created_at: str


class ManualDebtDeleteRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class SaleDebtWriteOffRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ArchiveClientRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def _manual_debt_snapshot(entry: ManualDebt) -> str:
    return json.dumps({"client_id": entry.counterparty_id, "amount": str(entry.amount), "description": entry.description}, ensure_ascii=False)


def _client_snapshot(client: Counterparty) -> str:
    return json.dumps({"name": client.name, "phone": client.phone}, ensure_ascii=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


session_dependency = Depends(get_session)
router = APIRouter()


@router.get("/audit")
async def list_audit_events(
    entity_type: str | None = None,
    _: User = Depends(require_roles("ADMIN")),
    session: AsyncSession = session_dependency,
) -> list[dict[str, str | int | None]]:
    query = (
        select(AuditEvent, User.full_name, User.username, Counterparty.name)
        .outerjoin(User, User.id == AuditEvent.actor_id)
        .outerjoin(Counterparty, Counterparty.id == AuditEvent.counterparty_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(500)
    )
    if entity_type:
        entity_types = [value.strip() for value in entity_type.split(",") if value.strip()]
        query = query.where(AuditEvent.entity_type.in_(entity_types))
    return [
        {
            "id": event.id,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "client_name": client_name or "",
            "actor_name": full_name or username or "Удалённый пользователь",
            "action": event.action,
            "reason": event.reason,
            "before_data": event.before_data or "",
            "after_data": event.after_data or "",
            "created_at": event.created_at.isoformat(),
        }
        for event, full_name, username, client_name in (await session.execute(query)).all()
    ]


@router.get("/list", response_model=list[ClientResponse])
async def list_clients(
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    as_of: date | None = None,
    _: User = Depends(require_section("clients")),
    session: AsyncSession = session_dependency,
) -> list[ClientResponse]:
    if as_of:
        end_of_day = datetime.combine(as_of, time.max, tzinfo=get_app_timezone())
        sales_total = select(func.coalesce(func.sum(Sale.total_amount), 0)).where(
            Sale.counterparty_id == Counterparty.id,
            Sale.created_at <= end_of_day,
        ).scalar_subquery()
        paid_total = select(func.coalesce(func.sum(CashTransaction.amount), 0)).where(
            CashTransaction.counterparty_id == Counterparty.id,
            CashTransaction.amount > 0,
            CashTransaction.created_at <= end_of_day,
        ).scalar_subquery()
        manual_debt_total = select(func.coalesce(func.sum(ManualDebt.amount), 0)).where(
            ManualDebt.counterparty_id == Counterparty.id,
            ManualDebt.created_at <= end_of_day,
        ).scalar_subquery()
        debt_total = sales_total - paid_total + manual_debt_total
    else:
        sales_debt_total = (
            select(func.coalesce(func.sum(Sale.debt_amount), 0))
            .where(Sale.counterparty_id == Counterparty.id)
            .scalar_subquery()
        )
        manual_debt_total = (
            select(func.coalesce(func.sum(ManualDebt.amount), 0))
            .where(ManualDebt.counterparty_id == Counterparty.id)
            .scalar_subquery()
        )
        debt_total = sales_debt_total + manual_debt_total
    archived = exists().where(
        AuditEvent.counterparty_id == Counterparty.id,
        AuditEvent.entity_type == "counterparty",
        AuditEvent.action == "ARCHIVED",
    )
    stmt = select(Counterparty, debt_total.label("debt_total")).where(~archived).order_by(Counterparty.name, Counterparty.id)
    if q and q.strip():
        search = f"%{q.strip()}%"
        stmt = stmt.where(or_(Counterparty.name.ilike(search), Counterparty.phone.ilike(search)))
    result = await session.execute(stmt.limit(max(1, min(limit, 500))).offset(max(0, offset)))
    clients = result.all()
    return [
        ClientResponse(
            id=client.id,
            name=client.name,
            phone=client.phone,
            current_debt=str(debt_total_value or 0),
        )
        for client, debt_total_value in clients
    ]


@router.get("/{client_id}/history", response_model=ClientHistoryResponse)
async def client_history(
    client_id: int,
    limit: int = 100,
    offset: int = 0,
    _: User = Depends(require_section("clients")),
    session: AsyncSession = session_dependency,
) -> ClientHistoryResponse:
    client = await session.get(Counterparty, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")

    page_limit = max(1, min(limit, 500))
    page_offset = max(0, offset)
    sales_result = await session.execute(
        select(Sale)
        .where(Sale.counterparty_id == client_id)
        .order_by(Sale.created_at.desc(), Sale.id.desc())
        .limit(page_limit)
        .offset(page_offset)
    )


    sales = sales_result.scalars().all()
    sale_ids = [sale.id for sale in sales]
    item_labels: dict[int, list[str]] = {sale_id: [] for sale_id in sale_ids}
    if sale_ids:
        item_result = await session.execute(
            select(SaleItem.sale_id, Item.name, SaleItem.qty)
            .join(Item, Item.id == SaleItem.item_id)
            .where(SaleItem.sale_id.in_(sale_ids))
        )
        for sale_id, item_name, qty in item_result:
            item_labels[sale_id].append(f"{item_name} x {qty}")

    payments_result = await session.execute(
        select(CashTransaction)
        .where(
            CashTransaction.counterparty_id == client_id,
            CashTransaction.amount > 0,
        )
        .order_by(CashTransaction.created_at.desc(), CashTransaction.id.desc())
        .limit(page_limit)
        .offset(page_offset)
    )
    payments = payments_result.scalars().all()
    sales_total = await session.scalar(
        select(func.coalesce(func.sum(Sale.total_amount), 0)).where(Sale.counterparty_id == client_id)
    )
    paid_total = await session.scalar(
        select(func.coalesce(func.sum(CashTransaction.amount), 0)).where(CashTransaction.counterparty_id == client_id)
    )
    calculated_debt = await session.scalar(
        select(func.coalesce(func.sum(Sale.debt_amount), 0)).where(Sale.counterparty_id == client_id)
    )
    manual_debt_total = await session.scalar(
        select(func.coalesce(func.sum(ManualDebt.amount), 0)).where(ManualDebt.counterparty_id == client_id)
    )
    return ClientHistoryResponse(
        client=ClientResponse(
            id=client.id,
            name=client.name,
            phone=client.phone,
            current_debt=str((calculated_debt or 0) + (manual_debt_total or 0)),
        ),
        sales=[ClientSaleHistoryResponse(
            id=sale.id,
            created_at=sale.created_at.isoformat(),
            total_amount=str(sale.total_amount),
            paid_amount=str(sale.paid_amount),
            debt_amount=str(sale.debt_amount),
            items=", ".join(item_labels[sale.id]),
        ) for sale in sales],
        payments=[ClientPaymentHistoryResponse(
            id=payment.id,
            created_at=payment.created_at.isoformat(),
            amount=str(payment.amount),
            payment_method=display_label(payment.payment_method.value),
            description=display_label(payment.description or ""),
        ) for payment in payments],
        sales_total=str(sales_total or 0),
        paid_total=str(paid_total or 0),
    )


@router.get("/{client_id}/manual-debts", response_model=list[ManualDebtResponse])
async def list_manual_debts(
    client_id: int,
    _: User = Depends(require_roles("ADMIN")),
    session: AsyncSession = session_dependency,
) -> list[ManualDebtResponse]:
    if await session.get(Counterparty, client_id) is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    entries = (await session.execute(
        select(ManualDebt)
        .where(ManualDebt.counterparty_id == client_id)
        .order_by(ManualDebt.created_at.desc(), ManualDebt.id.desc())
    )).scalars().all()
    return [ManualDebtResponse(
        id=entry.id,
        client_id=entry.counterparty_id,
        amount=str(entry.amount),
        description=entry.description,
        created_at=entry.created_at.isoformat(),
    ) for entry in entries]


@router.post("/manual-debts", response_model=ManualDebtResponse)
async def create_manual_debt(
    request: ManualDebtCreateRequest,
    user: User = Depends(require_roles("ADMIN")),
    session: AsyncSession = session_dependency,
) -> ManualDebtResponse:
    if await session.get(Counterparty, request.client_id) is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    entry = ManualDebt(
        counterparty_id=request.client_id,
        amount=request.amount,
        description=request.description.strip(),
    )
    session.add(entry)
    await session.flush()
    session.add(AuditEvent(
        entity_type="manual_debt", entity_id=entry.id, counterparty_id=entry.counterparty_id,
        actor_id=user.id, action="CREATED", reason=entry.description,
        after_data=_manual_debt_snapshot(entry),
    ))
    await session.commit()
    await session.refresh(entry)
    return ManualDebtResponse(
        id=entry.id,
        client_id=entry.counterparty_id,
        amount=str(entry.amount),
        description=entry.description,
        created_at=entry.created_at.isoformat(),
    )


@router.put("/manual-debts/{debt_id}", response_model=ManualDebtResponse)
async def update_manual_debt(
    debt_id: int,
    request: ManualDebtRequest,
    user: User = Depends(require_roles("ADMIN")),
    session: AsyncSession = session_dependency,
) -> ManualDebtResponse:
    entry = await session.get(ManualDebt, debt_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись долга не найдена")
    before_data = _manual_debt_snapshot(entry)
    entry.amount = request.amount
    entry.description = request.description.strip()
    session.add(AuditEvent(
        entity_type="manual_debt", entity_id=entry.id, counterparty_id=entry.counterparty_id,
        actor_id=user.id, action="UPDATED", reason="Изменение записи долга",
        before_data=before_data, after_data=_manual_debt_snapshot(entry),
    ))
    await session.commit()
    await session.refresh(entry)
    return ManualDebtResponse(
        id=entry.id,
        client_id=entry.counterparty_id,
        amount=str(entry.amount),
        description=entry.description,
        created_at=entry.created_at.isoformat(),
    )


@router.delete("/manual-debts/{debt_id}")
async def delete_manual_debt(
    debt_id: int,
    request: ManualDebtDeleteRequest,
    user: User = Depends(require_roles("ADMIN")),
    session: AsyncSession = session_dependency,
) -> dict[str, int | bool]:
    entry = await session.get(ManualDebt, debt_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись долга не найдена")
    session.add(AuditEvent(
        entity_type="manual_debt", entity_id=entry.id, counterparty_id=entry.counterparty_id,
        actor_id=user.id, action="DELETED", reason=request.reason.strip(),
        before_data=_manual_debt_snapshot(entry),
    ))
    await session.delete(entry)
    await session.commit()
    return {"id": debt_id, "deleted": True}


@router.post("/sale-debts/{sale_id}/write-off")
async def write_off_sale_debt(
    sale_id: int,
    request: SaleDebtWriteOffRequest,
    user: User = Depends(require_roles("ADMIN")),
    session: AsyncSession = session_dependency,
) -> dict[str, int | str | bool]:
    sale = await session.scalar(
        select(Sale).options(selectinload(Sale.counterparty)).where(Sale.id == sale_id)
    )
    if sale is None:
        raise HTTPException(status_code=404, detail="Продажа не найдена")
    if sale.debt_amount <= 0:
        raise HTTPException(status_code=409, detail="У продажи нет непогашенного долга")
    reason = request.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="Укажите причину списания долга")

    amount = sale.debt_amount
    before_data = json.dumps({"sale_id": sale.id, "debt_amount": str(amount)}, ensure_ascii=False)
    sale.debt_amount = Decimal(0)
    if sale.counterparty is not None:
        sale.counterparty.current_debt = max(Decimal(0), sale.counterparty.current_debt - amount)
    session.add(AuditEvent(
        entity_type="sale_debt", entity_id=sale.id,
        counterparty_id=sale.counterparty_id, actor_id=user.id,
        action="WRITTEN_OFF", reason=reason, before_data=before_data,
        after_data=json.dumps({"sale_id": sale.id, "debt_amount": "0"}, ensure_ascii=False),
    ))
    await session.commit()
    return {"sale_id": sale.id, "written_off": True, "amount": str(amount)}


@router.post("/{client_id}/payments", response_model=ClientPaymentResponse)
async def repay_client(
    client_id: int,
    request: ClientPaymentCreateRequest,
    _: User = Depends(require_section("clients")),
    session: AsyncSession = session_dependency,
) -> ClientPaymentResponse:
    result = await repay_client_debt(
        session,
        client_id,
        request.amount,
        request.payment_method,
        request.description,
    )
    await session.commit()
    return ClientPaymentResponse(
        payment_id=result["payment_id"],
        client_id=result["client_id"],
        amount=str(result["amount"]),
        remaining_debt=str(result["remaining_debt"]),
        allocations=[
            {"sale_id": item["sale_id"], "amount": str(item["amount"])}
            for item in result["allocations"]
        ],
    )


@router.post("/create", response_model=ClientResponse)
async def create_client(
    request: ClientCreateRequest,
    user: User = Depends(require_section("clients")),
    session: AsyncSession = session_dependency,
) -> ClientResponse:
    if "clients_edit" not in user_permissions(user):
        raise HTTPException(status_code=403, detail="Администратор не предоставил право изменять клиентов")
    existing = await session.scalar(select(Counterparty).where(Counterparty.name == request.name))
    if existing is not None:
        raise HTTPException(status_code=400, detail="Client already exists")
    client = Counterparty(name=request.name, phone=request.phone, current_debt=Decimal(0))
    session.add(client)
    await session.flush()
    await session.commit()
    return ClientResponse(id=client.id, name=client.name, phone=client.phone, current_debt=str(client.current_debt))


@router.patch("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: int,
    request: ClientUpdateRequest,
    user: User = Depends(require_section("clients")),
    session: AsyncSession = session_dependency,
) -> ClientResponse:
    if "clients_edit" not in user_permissions(user):
        raise HTTPException(status_code=403, detail="Администратор не предоставил право изменять клиентов")
    client = await session.get(Counterparty, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    duplicate = await session.scalar(select(Counterparty).where(Counterparty.name == request.name, Counterparty.id != client_id))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Клиент с таким именем уже существует")
    before_data = _client_snapshot(client)
    client.name = request.name
    client.phone = request.phone
    session.add(AuditEvent(
        entity_type="counterparty", entity_id=client.id, counterparty_id=client.id,
        actor_id=user.id, action="UPDATED", reason="Изменение карточки клиента",
        before_data=before_data, after_data=_client_snapshot(client),
    ))
    await session.commit()
    return ClientResponse(id=client.id, name=client.name, phone=client.phone, current_debt=str(client.current_debt or 0))


@router.post("/{client_id}/archive")
async def archive_client(
    client_id: int,
    request: ArchiveClientRequest,
    user: User = Depends(require_section("clients")),
    session: AsyncSession = session_dependency,
) -> dict[str, int | bool]:
    if user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Архивировать клиента может только администратор")
    client = await session.get(Counterparty, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    already_archived = await session.scalar(select(AuditEvent.id).where(
        AuditEvent.counterparty_id == client_id,
        AuditEvent.entity_type == "counterparty",
        AuditEvent.action == "ARCHIVED",
    ).limit(1))
    if already_archived:
        raise HTTPException(status_code=409, detail="Клиент уже находится в архиве")
    session.add(AuditEvent(
        entity_type="counterparty", entity_id=client.id, counterparty_id=client.id,
        actor_id=user.id, action="ARCHIVED", reason=request.reason.strip(),
        before_data=_client_snapshot(client),
    ))
    await session.commit()
    return {"id": client_id, "archived": True}
