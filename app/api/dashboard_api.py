from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import require_section
from app.db import async_session
from app.models.schema import Order, OrderItem, OrderStatus, Sale, User
from app.services.dashboard import build_dashboard_summary
from app.services.timezone import get_app_timezone


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


@router.get("/sellers")
async def dashboard_sellers(session: AsyncSession = session_dependency) -> list[dict[str, int | str]]:
    employees = (await session.execute(
        select(User).order_by(User.is_active.desc(), User.full_name, User.username)
    )).scalars().all()
    return [{"id": employee.id, "name": employee.full_name or employee.username, "is_active": employee.is_active} for employee in employees]


@router.get("/seller-performance")
async def seller_performance(
    seller_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    session: AsyncSession = session_dependency,
) -> dict:
    seller = await session.get(User, seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")

    tz = get_app_timezone()
    sale_timestamp = func.coalesce(Sale.created_at, Order.delivered_at, Order.created_at)
    sales_query = select(Order, Sale).outerjoin(Sale, Sale.id == Order.sale_id).options(
        selectinload(Order.client),
        selectinload(Order.referrer),
        selectinload(Order.items).selectinload(OrderItem.item),
    ).where(
        Order.courier_id == seller_id,
        Order.status == OrderStatus.DELIVERED,
    ).order_by(sale_timestamp.desc(), Order.id.desc())
    if date_from:
        sales_query = sales_query.where(sale_timestamp >= datetime.combine(date_from, time.min, tzinfo=tz))
    if date_to:
        sales_query = sales_query.where(sale_timestamp <= datetime.combine(date_to, time.max, tzinfo=tz))
    sales = (await session.execute(sales_query)).all()

    source_totals: dict[tuple[int | None, str], dict[str, int | str | Decimal]] = {}
    order_rows = []
    total_amount = Decimal(0)
    for order, sale in sales:
        if sale is not None:
            amount = Decimal(sale.total_amount or 0)
            sale_created_at = sale.created_at
        else:
            order_total = sum(
                (line.quantity * line.price - (line.discount or Decimal(0)) for line in order.items),
                Decimal(0),
            ) - (order.discount_amount or Decimal(0))
            amount = max(Decimal(0), order_total).quantize(Decimal("0.01"))
            sale_created_at = order.delivered_at or order.created_at
        if amount <= 0:
            continue
        source_name = (
            order.referrer.full_name or order.referrer.username
            if order.referrer else order.referred_by or "Не указан"
        )
        source_key = (order.referred_by_user_id, source_name)
        source_row = source_totals.setdefault(source_key, {
            "referrer_id": order.referred_by_user_id,
            "referrer_name": source_name,
            "total_amount": Decimal(0),
            "sales_count": 0,
        })
        source_row["total_amount"] = Decimal(source_row["total_amount"]) + amount
        source_row["sales_count"] = int(source_row["sales_count"]) + 1
        total_amount += amount
        order_rows.append({
            "order_id": order.id,
            "invoice_number": order.invoice_number or "",
            "client_name": order.client.name if order.client else "",
            "referrer_id": order.referred_by_user_id,
            "referrer_name": source_name,
            "total_amount": amount.quantize(Decimal("0.01")),
            "created_at": sale_created_at,
            "items": "; ".join(
                f"{line.item.name} × {line.quantity} {line.item.unit}" for line in order.items
            ),
        })

    referrers = sorted(
        ({**row, "total_amount": Decimal(row["total_amount"]).quantize(Decimal("0.01"))} for row in source_totals.values()),
        key=lambda row: (-Decimal(row["total_amount"]), str(row["referrer_name"]).casefold()),
    )
    return {
        "seller_id": seller.id,
        "seller_name": seller.full_name or seller.username,
        "total_amount": total_amount.quantize(Decimal("0.01")),
        "sales_count": len(order_rows),
        "by_referrer": referrers,
        "orders": order_rows,
    }
