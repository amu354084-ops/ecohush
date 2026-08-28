from __future__ import annotations

from decimal import Decimal
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import require_roles, require_section
from app.db import async_session
from app.models.schema import User
from app.models.schema import CashTransaction, Counterparty, Item, PaymentMethod, Sale, SaleItem, User
from app.services.localization import display_label
from app.services.sales import repay_client_debt


class ClientCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=64)


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


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


session_dependency = Depends(get_session)
router = APIRouter()


@router.get("/list", response_model=list[ClientResponse])
async def list_clients(
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _: User = Depends(require_section("clients")),
    session: AsyncSession = session_dependency,
) -> list[ClientResponse]:
    debt_total = (
        select(func.coalesce(func.sum(Sale.debt_amount), 0))
        .where(Sale.counterparty_id == Counterparty.id)
        .scalar_subquery()
    )
    stmt = select(Counterparty, debt_total.label("debt_total")).order_by(Counterparty.name, Counterparty.id)
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
    return ClientHistoryResponse(
        client=ClientResponse(
            id=client.id,
            name=client.name,
            phone=client.phone,
            current_debt=str(calculated_debt or 0),
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
    _: User = Depends(require_section("clients")),
    session: AsyncSession = session_dependency,
) -> ClientResponse:
    existing = await session.scalar(select(Counterparty).where(Counterparty.name == request.name))
    if existing is not None:
        raise HTTPException(status_code=400, detail="Client already exists")
    client = Counterparty(name=request.name, phone=request.phone, current_debt=Decimal(0))
    session.add(client)
    await session.flush()
    await session.commit()
    return ClientResponse(id=client.id, name=client.name, phone=client.phone, current_debt=str(client.current_debt))
