from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import (
    CashTransaction,
    CashTransactionType,
    OverheadExpense,
    PayrollEntry,
    PayrollPenalty,
    Sale,
    SaleItem,
    SaleItemBatchAllocation,
)


async def build_pnl_summary(
    session: AsyncSession,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    sales_stmt = select(func.coalesce(func.sum(Sale.total_amount), 0))
    if date_from:
        sales_stmt = sales_stmt.where(Sale.created_at >= date_from)
    if date_to:
        sales_stmt = sales_stmt.where(Sale.created_at <= date_to)
    result = await session.execute(sales_stmt)
    revenue = Decimal(result.scalar() or 0).quantize(Decimal("0.01"))

    cogs_stmt = (
        select(func.coalesce(func.sum(SaleItemBatchAllocation.qty * SaleItemBatchAllocation.unit_cost), 0))
        .join(SaleItem, SaleItem.id == SaleItemBatchAllocation.sale_item_id)
        .join(Sale, Sale.id == SaleItem.sale_id)
    )
    if date_from:
        cogs_stmt = cogs_stmt.where(Sale.created_at >= date_from)
    if date_to:
        cogs_stmt = cogs_stmt.where(Sale.created_at <= date_to)
    allocated_result = await session.execute(cogs_stmt)
    allocated_cogs = Decimal(allocated_result.scalar() or 0)

    legacy_cogs_stmt = (
        select(func.coalesce(func.sum(SaleItem.qty * SaleItem.cost_price), 0))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(~exists().where(SaleItemBatchAllocation.sale_item_id == SaleItem.id))
    )
    if date_from:
        legacy_cogs_stmt = legacy_cogs_stmt.where(Sale.created_at >= date_from)
    if date_to:
        legacy_cogs_stmt = legacy_cogs_stmt.where(Sale.created_at <= date_to)
    legacy_result = await session.execute(legacy_cogs_stmt)
    cogs = (allocated_cogs + Decimal(legacy_result.scalar() or 0)).quantize(Decimal("0.01"))

    overheads_stmt = select(func.coalesce(func.sum(OverheadExpense.amount), 0))
    if date_from:
        overheads_stmt = overheads_stmt.where(OverheadExpense.created_at >= date_from)
    if date_to:
        overheads_stmt = overheads_stmt.where(OverheadExpense.created_at <= date_to)
    result = await session.execute(overheads_stmt)
    overheads = Decimal(result.scalar() or 0).quantize(Decimal("0.01"))

    profit = (revenue - cogs - overheads).quantize(Decimal("0.01"))

    payroll_stmt = select(func.coalesce(func.sum(PayrollEntry.total_amount), 0))
    if date_from:
        payroll_stmt = payroll_stmt.where(PayrollEntry.period >= date_from.strftime("%Y-%m"))
    if date_to:
        payroll_stmt = payroll_stmt.where(PayrollEntry.period <= date_to.strftime("%Y-%m"))
    payroll = Decimal((await session.execute(payroll_stmt)).scalar() or 0).quantize(Decimal("0.01"))
    penalty_stmt = select(func.coalesce(func.sum(PayrollPenalty.amount), 0))
    if date_from:
        penalty_stmt = penalty_stmt.where(PayrollPenalty.period >= date_from.strftime("%Y-%m"))
    if date_to:
        penalty_stmt = penalty_stmt.where(PayrollPenalty.period <= date_to.strftime("%Y-%m"))
    penalties = Decimal((await session.execute(penalty_stmt)).scalar() or 0).quantize(Decimal("0.01"))
    net_payroll = payroll - penalties
    profit = (revenue - cogs - overheads - payroll - penalties).quantize(Decimal("0.01"))
    gross_profit = (revenue - cogs).quantize(Decimal("0.01"))
    markup = (gross_profit / cogs * Decimal("100")).quantize(Decimal("0.01")) if cogs else Decimal("0.00")

    cash_stmt = select(
        func.coalesce(func.sum(case((CashTransaction.type == CashTransactionType.INCOME, CashTransaction.amount), else_=0)), 0),
        func.coalesce(func.sum(case((CashTransaction.type == CashTransactionType.EXPENSE, CashTransaction.amount), else_=0)), 0),
    )
    if date_from:
        cash_stmt = cash_stmt.where(CashTransaction.created_at >= date_from)
    if date_to:
        cash_stmt = cash_stmt.where(CashTransaction.created_at <= date_to)
    cash_income, cash_expenses = (await session.execute(cash_stmt)).one()
    cash_income = Decimal(cash_income or 0).quantize(Decimal("0.01"))
    cash_expenses = Decimal(cash_expenses or 0).quantize(Decimal("0.01"))
    company_balance = (cash_income - cash_expenses).quantize(Decimal("0.01"))

    return {
        "revenue": revenue,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "markup": markup,
        "overheads": overheads,
        "payroll": payroll,
        "penalties": penalties,
        "net_payroll": net_payroll,
        "cash_income": cash_income,
        "cash_expenses": cash_expenses,
        "company_balance": company_balance,
        "profit": profit,
    }
