from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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
from app.services.timezone import get_app_timezone, to_db_datetime

LEGACY_PRODUCTION_OVERHEAD_CATEGORY = "Production overhead"


def returned_sale_condition():
    """True for sales that were fully returned.

    A return sets ``total_amount`` to zero but keeps the sale lines, so their cost must
    not be counted as COGS any more.  A sale given away with a 100 % line discount also
    has a zero total but must keep its cost, hence the discount check.
    """
    line = aliased(SaleItem)
    return (Sale.total_amount == 0) & exists().where(line.sale_id == Sale.id, line.discount_percent < 100)


def production_overhead_duplicate_condition():
    """Old production runs stored their overhead both in the batch cost and as an expense."""
    return (OverheadExpense.category == LEGACY_PRODUCTION_OVERHEAD_CATEGORY) & OverheadExpense.production_run_id.is_(None)


async def build_pnl_summary(
    session: AsyncSession,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    # Payroll is stored per month ("YYYY-MM"), so its period is taken in local time.
    app_tz = get_app_timezone()
    payroll_from = date_from.astimezone(app_tz) if isinstance(date_from, datetime) and date_from.tzinfo else date_from
    payroll_to = date_to.astimezone(app_tz) if isinstance(date_to, datetime) and date_to.tzinfo else date_to
    date_from = to_db_datetime(date_from)
    date_to = to_db_datetime(date_to)
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
        .where(~returned_sale_condition())
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
        .where(~returned_sale_condition())
    )
    if date_from:
        legacy_cogs_stmt = legacy_cogs_stmt.where(Sale.created_at >= date_from)
    if date_to:
        legacy_cogs_stmt = legacy_cogs_stmt.where(Sale.created_at <= date_to)
    legacy_result = await session.execute(legacy_cogs_stmt)
    cogs = (allocated_cogs + Decimal(legacy_result.scalar() or 0)).quantize(Decimal("0.01"))

    overheads_stmt = select(func.coalesce(func.sum(OverheadExpense.amount), 0)).where(
        ~production_overhead_duplicate_condition()
    )
    if date_from:
        overheads_stmt = overheads_stmt.where(OverheadExpense.created_at >= date_from)
    if date_to:
        overheads_stmt = overheads_stmt.where(OverheadExpense.created_at <= date_to)
    result = await session.execute(overheads_stmt)
    overheads = Decimal(result.scalar() or 0).quantize(Decimal("0.01"))

    payroll_stmt = select(func.coalesce(func.sum(PayrollEntry.total_amount), 0))
    if payroll_from is not None:
        period_from = payroll_from.strftime("%Y-%m") if isinstance(payroll_from, datetime) else str(payroll_from)[:7]
        payroll_stmt = payroll_stmt.where(PayrollEntry.period >= period_from)
    if payroll_to is not None:
        period_to = payroll_to.strftime("%Y-%m") if isinstance(payroll_to, datetime) else str(payroll_to)[:7]
        payroll_stmt = payroll_stmt.where(PayrollEntry.period <= period_to)
    payroll = Decimal((await session.execute(payroll_stmt)).scalar() or 0).quantize(Decimal("0.01"))
    penalty_stmt = select(func.coalesce(func.sum(PayrollPenalty.amount), 0))
    if payroll_from is not None:
        period_from = payroll_from.strftime("%Y-%m") if isinstance(payroll_from, datetime) else str(payroll_from)[:7]
        penalty_stmt = penalty_stmt.where(PayrollPenalty.period >= period_from)
    if payroll_to is not None:
        period_to = payroll_to.strftime("%Y-%m") if isinstance(payroll_to, datetime) else str(payroll_to)[:7]
        penalty_stmt = penalty_stmt.where(PayrollPenalty.period <= period_to)
    penalties = Decimal((await session.execute(penalty_stmt)).scalar() or 0).quantize(Decimal("0.01"))
    operating_expenses = (overheads + payroll + penalties).quantize(Decimal("0.01"))
    net_payroll = payroll - penalties
    gross_profit = (revenue - cogs).quantize(Decimal("0.01"))
    profit = (revenue - cogs - operating_expenses).quantize(Decimal("0.01"))
    markup = (gross_profit / cogs * Decimal("100")).quantize(Decimal("0.01")) if cogs else Decimal("0.00")
    gross_margin = (gross_profit / revenue * Decimal("100")).quantize(Decimal("0.01")) if revenue else Decimal("0.00")

    cash_stmt = select(
        func.coalesce(func.sum(case((CashTransaction.type == CashTransactionType.INCOME, CashTransaction.amount), else_=0)), 0),
        func.coalesce(
            func.sum(
                case(
                    (
                        (CashTransaction.type == CashTransactionType.EXPENSE)
                        & (CashTransaction.is_company_expense.is_(True)),
                        CashTransaction.amount,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
        func.coalesce(
            func.sum(
                case(
                    (
                        (CashTransaction.type == CashTransactionType.EXPENSE)
                        & (CashTransaction.is_company_expense.is_(False)),
                        CashTransaction.amount,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
    )
    if date_from:
        cash_stmt = cash_stmt.where(CashTransaction.created_at >= date_from)
    if date_to:
        cash_stmt = cash_stmt.where(CashTransaction.created_at <= date_to)
    cash_income, cash_expenses, note_expenses = (await session.execute(cash_stmt)).one()
    cash_income = Decimal(cash_income or 0).quantize(Decimal("0.01"))
    cash_expenses = Decimal(cash_expenses or 0).quantize(Decimal("0.01"))
    note_expenses = Decimal(note_expenses or 0).quantize(Decimal("0.01"))
    company_balance = (cash_income - cash_expenses).quantize(Decimal("0.01"))

    return {
        "revenue": revenue,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "gross_margin": gross_margin,
        "markup": markup,
        "overheads": overheads,
        "operating_expenses": operating_expenses,
        "payroll": payroll,
        "penalties": penalties,
        "net_payroll": net_payroll,
        "cash_income": cash_income,
        "cash_expenses": cash_expenses,
        "note_expenses": note_expenses,
        "company_balance": company_balance,
        "profit": profit,
    }
