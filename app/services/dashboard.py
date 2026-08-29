from __future__ import annotations

from decimal import Decimal
from typing import Any

from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import Batch, Counterparty, Item, ItemType, Sale, SaleItem, SaleItemBatchAllocation
from app.services.reports import build_pnl_summary


async def build_dashboard_summary(session: AsyncSession) -> dict[str, Any]:
    sales_result = await session.execute(select(Sale))
    sales = sales_result.scalars().all()

    items_result = await session.execute(select(Item))
    items = items_result.scalars().all()

    batches_result = await session.execute(select(Batch))
    batches = batches_result.scalars().all()

    pnl = await build_pnl_summary(session)
    income = pnl["revenue"]
    expense = pnl["cogs"] + pnl["overheads"] + pnl["net_payroll"]
    profit = pnl["profit"]

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

    today = datetime.now(timezone.utc).date()
    chart_start = today - timedelta(days=89)
    daily_result = await session.execute(
        select(
            func.date(Sale.created_at).label("day"),
            func.coalesce(func.sum(Sale.total_amount), 0).label("income"),
        )
        .where(Sale.created_at >= datetime.combine(chart_start, datetime.min.time(), tzinfo=timezone.utc))
        .group_by(func.date(Sale.created_at))
        .order_by(func.date(Sale.created_at))
    )
    daily_sales = {
        str(row.day): Decimal(row.income or 0).quantize(Decimal("0.01"))
        for row in daily_result
    }
    allocation_flow_result = await session.execute(
        select(
            func.date(Sale.created_at).label("day"),
            func.coalesce(
                func.sum(
                    SaleItemBatchAllocation.qty * SaleItemBatchAllocation.unit_cost
                ),
                0,
            ).label("expense"),
        )
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .join(SaleItemBatchAllocation, SaleItemBatchAllocation.sale_item_id == SaleItem.id)
        .where(Sale.created_at >= datetime.combine(chart_start, datetime.min.time(), tzinfo=timezone.utc))
        .group_by(func.date(Sale.created_at))
        .order_by(func.date(Sale.created_at))
    )
    daily_cogs = {str(row.day): Decimal(row.expense or 0) for row in allocation_flow_result}
    legacy_flow_result = await session.execute(
        select(
            func.date(Sale.created_at).label("day"),
            func.coalesce(func.sum(SaleItem.qty * SaleItem.cost_price), 0).label("expense"),
        )
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .where(
            Sale.created_at >= datetime.combine(chart_start, datetime.min.time(), tzinfo=timezone.utc),
            ~exists().where(SaleItemBatchAllocation.sale_item_id == SaleItem.id),
        )
        .group_by(func.date(Sale.created_at))
    )
    for row in legacy_flow_result:
        day = str(row.day)
        daily_cogs[day] = daily_cogs.get(day, Decimal(0)) + Decimal(row.expense or 0)
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
    top_clients_result = await session.execute(
        select(
            Counterparty.id.label("client_id"),
            Counterparty.name.label("client_name"),
            Counterparty.phone.label("phone"),
            func.coalesce(func.sum(Sale.total_amount), 0).label("total_amount"),
            func.count(Sale.id).label("sales_count"),
        )
        .join(Sale, Sale.counterparty_id == Counterparty.id)
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

    return {
        "sales_count": len(sales),
        "production_count": len([b for b in batches if b.remaining_qty > 0]),
        "raw_material_count": len([item for item in items if item.type == ItemType.RAW]),
        "finished_items_count": len([item for item in items if item.type == ItemType.FINAL]),
        "total_stock_qty": total_stock_qty,
        "stock_qty": total_stock_qty,
        "low_stock_items": len(low_stock_details),
        "low_stock_details": low_stock_details,
        "income": income,
        "expense": expense,
        "profit": profit,
        "revenue": pnl["revenue"],
        "cogs": pnl["cogs"],
        "overheads": pnl["overheads"],
        "payroll": pnl["payroll"],
        "penalties": pnl["penalties"],
        "net_payroll": pnl["net_payroll"],
        "cash_income": pnl["cash_income"],
        "cash_expenses": pnl["cash_expenses"],
        "company_balance": pnl["company_balance"],
        "daily_sales": [
            {"day": day.isoformat(), "income": daily_sales.get(day.isoformat(), Decimal("0.00"))}
            for day in (chart_start + timedelta(days=offset) for offset in range(90))
        ],
        "daily_finance": [
            {
                "day": day.isoformat(),
                **daily_sales_flow.get(day.isoformat(), {"income": Decimal("0.00"), "expense": Decimal("0.00")}),
            }
            for day in (chart_start + timedelta(days=offset) for offset in range(90))
        ],
        "recent_sales": recent_sales,
        "top_clients": top_clients,
    }
