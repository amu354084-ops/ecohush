from __future__ import annotations

from decimal import Decimal
from typing import Any

from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import Batch, Counterparty, Item, ItemType, Sale, SaleItem, SaleItemBatchAllocation
from app.services.reports import build_pnl_summary
from app.services.timezone import get_app_timezone


def _to_app_timezone(value: datetime, app_timezone) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(app_timezone)


async def build_dashboard_summary(
    session: AsyncSession,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    sales_stmt = select(Sale)
    if date_from:
        sales_stmt = sales_stmt.where(Sale.created_at >= date_from)
    if date_to:
        sales_stmt = sales_stmt.where(Sale.created_at <= date_to)
    sales_result = await session.execute(sales_stmt)
    sales = sales_result.scalars().all()

    items_result = await session.execute(select(Item))
    items = items_result.scalars().all()

    batches_result = await session.execute(select(Batch))
    batches = batches_result.scalars().all()

    pnl = await build_pnl_summary(session, date_from, date_to)
    income = pnl["revenue"]
    expense = pnl["operating_expenses"]
    profit = pnl["profit"]
    financial_check = (
        pnl["revenue"] - pnl["cogs"] - pnl["operating_expenses"] - pnl["profit"]
    ).quantize(Decimal("0.01"))
    if abs(financial_check) > Decimal("0.01"):
        raise ValueError("Dashboard financial totals are inconsistent")

    total_stock_qty = sum((batch.remaining_qty or Decimal("0")) for batch in batches)
    stock_by_item: dict[int, Decimal] = {}
    for batch in batches:
        if batch.item_id is None:
            continue
        stock_by_item[batch.item_id] = stock_by_item.get(batch.item_id, Decimal("0")) + (
            batch.remaining_qty or Decimal("0")
        )

    low_stock_details = [
        {
            "item_id": item.id,
            "code": item.code,
            "name": item.name,
            "unit": item.unit,
            "remaining_qty": str(stock_by_item.get(item.id, Decimal("0"))),
            "min_stock": str(item.min_stock),
        }
        for item in items
        if item.min_stock is not None
        and item.min_stock > 0
        and stock_by_item.get(item.id, Decimal("0")) <= Decimal(item.min_stock)
    ]
    low_stock_details.sort(key=lambda item: (item["name"].casefold(), item["code"].casefold()))

    tz = get_app_timezone()
    today = datetime.now(tz).date()
    default_chart_start = today - timedelta(days=89)
    chart_start = date_from.date() if date_from else default_chart_start
    chart_end = date_to.date() if date_to else today

    chart_start_dt = datetime.combine(chart_start, datetime.min.time(), tzinfo=tz)
    chart_end_dt = datetime.combine(chart_end, datetime.max.time(), tzinfo=tz)

    daily_sales: dict[str, Decimal] = {}
    daily_result = await session.execute(
        select(Sale.created_at, Sale.total_amount).where(
            Sale.created_at >= chart_start_dt,
            Sale.created_at <= chart_end_dt,
        )
    )
    for created_at, total_amount in daily_result:
        local_created_at = _to_app_timezone(created_at, tz)
        day = local_created_at.date().isoformat()
        daily_sales[day] = daily_sales.get(day, Decimal("0")) + Decimal(total_amount or 0)
    daily_sales = {day: amount.quantize(Decimal("0.01")) for day, amount in daily_sales.items()}

    daily_cogs: dict[str, Decimal] = {}
    allocation_flow_result = await session.execute(
        select(
            Sale.created_at,
            SaleItemBatchAllocation.qty * SaleItemBatchAllocation.unit_cost,
        )
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .join(SaleItemBatchAllocation, SaleItemBatchAllocation.sale_item_id == SaleItem.id)
        .where(Sale.created_at >= chart_start_dt, Sale.created_at <= chart_end_dt)
    )
    for created_at, amount in allocation_flow_result:
        local_created_at = _to_app_timezone(created_at, tz)
        day = local_created_at.date().isoformat()
        daily_cogs[day] = daily_cogs.get(day, Decimal("0")) + Decimal(amount or 0)

    legacy_flow_result = await session.execute(
        select(Sale.created_at, SaleItem.qty * SaleItem.cost_price)
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .where(
            Sale.created_at >= chart_start_dt,
            Sale.created_at <= chart_end_dt,
            ~exists().where(SaleItemBatchAllocation.sale_item_id == SaleItem.id),
        )
    )
    for created_at, amount in legacy_flow_result:
        local_created_at = _to_app_timezone(created_at, tz)
        day = local_created_at.date().isoformat()
        daily_cogs[day] = daily_cogs.get(day, Decimal("0")) + Decimal(amount or 0)
    daily_sales_flow = {
        day: {
            "income": daily_sales.get(day, Decimal(0)),
            "expense": expense.quantize(Decimal("0.01")),
        }
        for day, expense in daily_cogs.items()
    }
    for day, income in daily_sales.items():
        daily_sales_flow.setdefault(day, {"income": income, "expense": Decimal("0.00")})
    recent_result = await session.execute(
        select(Sale)
        .options(selectinload(Sale.counterparty))
        .where(*(
            condition
            for condition in (
                Sale.created_at >= date_from if date_from else None,
                Sale.created_at <= date_to if date_to else None,
            )
            if condition is not None
        ))
        .order_by(Sale.created_at.desc(), Sale.id.desc())
        .limit(5)
    )
    recent_sales = [
        {
            "sale_id": sale.id,
            "client_id": sale.counterparty_id,
            "client_name": sale.counterparty.name if sale.counterparty else "Розничный клиент",
            "total_amount": sale.total_amount,
            "paid_amount": sale.paid_amount,
            "debt_amount": sale.debt_amount,
            "created_at": sale.created_at,
        }
        for sale in recent_result.scalars().all()
    ]
    top_clients_stmt = (
        select(
            Counterparty.id.label("client_id"),
            Counterparty.name.label("client_name"),
            Counterparty.phone.label("phone"),
            func.coalesce(func.sum(Sale.total_amount), 0).label("total_amount"),
            func.count(Sale.id).label("sales_count"),
        )
        .join(Sale, Sale.counterparty_id == Counterparty.id)
    )
    if date_from:
        top_clients_stmt = top_clients_stmt.where(Sale.created_at >= date_from)
    if date_to:
        top_clients_stmt = top_clients_stmt.where(Sale.created_at <= date_to)
    top_clients_result = await session.execute(
        top_clients_stmt
        .group_by(Counterparty.id, Counterparty.name, Counterparty.phone)
        .order_by(func.sum(Sale.total_amount).desc(), Counterparty.name)
        .limit(10)
    )
    top_clients = [
        {
            "client_id": row.client_id,
            "client_name": row.client_name,
            "phone": row.phone or "",
            "total_amount": Decimal(row.total_amount or 0).quantize(Decimal("0.01")),
            "sales_count": row.sales_count,
        }
        for row in top_clients_result
    ]

    chart_values = [
        {"key": "cogs", "label": "Себестоимость", "value": pnl["cogs"], "color": "#EF4444"},
        {"key": "operating_expenses", "label": "Все расходы", "value": pnl["operating_expenses"], "color": "#F97316"},
        {
            "key": "net_profit",
            "label": "Чистая прибыль" if pnl["profit"] >= 0 else "Убыток",
            "value": pnl["profit"],
            "color": "#8B5CF6",
        },
    ]

    return {
        "sales_count": len(sales),
        "production_count": len([
            batch for batch in batches
            if batch.remaining_qty > 0
            and (not date_from or _to_app_timezone(batch.created_at, tz) >= date_from.astimezone(tz))
            and (not date_to or _to_app_timezone(batch.created_at, tz) <= date_to.astimezone(tz))
        ]),
        "raw_material_count": len([item for item in items if item.type == ItemType.RAW]),
        "finished_items_count": len([item for item in items if item.type == ItemType.FINAL]),
        "total_stock_qty": total_stock_qty,
        "stock_qty": total_stock_qty,
        "low_stock_items": len(low_stock_details),
        "low_stock_details": low_stock_details,
        "income": income,
        "expense": expense,
        "profit": profit,
        "net_profit": pnl["profit"],
        "gross_profit": pnl["gross_profit"],
        "gross_margin": pnl["gross_margin"],
        "revenue": pnl["revenue"],
        "cogs": pnl["cogs"],
        "operating_expenses": pnl["operating_expenses"],
        "financial_check": financial_check,
        "period": {
            "from": date_from.date().isoformat() if date_from else None,
            "to": date_to.date().isoformat() if date_to else None,
        },
        "chart": {
            "revenue": pnl["revenue"],
            "negative_profit": pnl["profit"] < 0,
            "values": chart_values,
        },
        "expense_breakdown": {
            "overheads": pnl["overheads"],
            "payroll": pnl["payroll"],
            "penalties": pnl["penalties"],
        },
        "overheads": pnl["overheads"],
        "payroll": pnl["payroll"],
        "penalties": pnl["penalties"],
        "net_payroll": pnl["net_payroll"],
        "cash_income": pnl["cash_income"],
        "cash_expenses": pnl["cash_expenses"],
        "company_balance": pnl["company_balance"],
        "daily_sales": [
            {"day": day.isoformat(), "income": daily_sales.get(day.isoformat(), Decimal("0.00"))}
            for day in (chart_start + timedelta(days=offset) for offset in range((chart_end - chart_start).days + 1))
        ],
        "daily_finance": [
            {
                "day": day.isoformat(),
                **daily_sales_flow.get(day.isoformat(), {"income": Decimal("0.00"), "expense": Decimal("0.00")}),
            }
            for day in (chart_start + timedelta(days=offset) for offset in range((chart_end - chart_start).days + 1))
        ],
        "recent_sales": recent_sales,
        "top_clients": top_clients,
    }
