from __future__ import annotations

from datetime import date, datetime, time, timezone
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import require_section
from app.db import async_session
from app.models.schema import PayrollEntry, PayrollPenalty, Sale, SaleItem, OverheadExpense, User
from app.services.localization import display_label
from app.services.reports import build_pnl_summary
from app.services.google_sheets import sync_report_sections


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session


session_dependency = Depends(get_session)
router = APIRouter(dependencies=[Depends(require_section("reports"))])


def _period_datetime(value: date, boundary: time) -> datetime:
    return datetime.combine(value, boundary, tzinfo=timezone.utc)


def _excel_safe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: value.replace(tzinfo=None) if isinstance(value, datetime) and value.tzinfo else value
            for key, value in row.items()
        }
        for row in rows
    ]


async def build_report_sections(
    session: AsyncSession,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, list[dict[str, Any]]]:
    sales_rows = []
    sales_stmt = select(Sale).options(
        selectinload(Sale.counterparty),
        selectinload(Sale.sale_items).selectinload(SaleItem.item),
    ).order_by(Sale.created_at, Sale.id)
    if date_from:
        sales_stmt = sales_stmt.where(Sale.created_at >= _period_datetime(date_from, time.min))
    if date_to:
        sales_stmt = sales_stmt.where(Sale.created_at <= _period_datetime(date_to, time.max))
    result = await session.execute(sales_stmt)
    for sale in result.scalars().all():
        sales_rows.append({
            "Продажа №": sale.id,
            "Клиент": sale.counterparty.name if sale.counterparty else "Розничный клиент",
            "Телефон клиента": sale.counterparty.phone if sale.counterparty else "",
            "Товары": "; ".join(
                f"{item.item.name} x {item.qty} по {item.unit_price}"
                for item in sale.sale_items
            ),
            "Сумма": float(sale.total_amount),
            "Оплачено": float(sale.paid_amount),
            "Задолженность": float(sale.debt_amount),
            "Способ оплаты": getattr(sale.payment_method, "value", sale.payment_method) or "Не указано",
            "Дата и время": sale.created_at,
        })

    sale_ids = [row["Продажа №"] for row in sales_rows]
    sale_items_stmt = (
        select(SaleItem).where(SaleItem.sale_id.in_(sale_ids))
        if sale_ids
        else select(SaleItem).where(SaleItem.id < 0)
    )
    result = await session.execute(sale_items_stmt)
    sale_items_rows = [
        {
            "Продажа №": item.sale_id,
            "Товар №": item.item_id,
            "Товар": item.item.name if item.item else "",
            "Количество": float(item.qty),
            "Цена": float(item.unit_price),
            "Себестоимость": float(item.cost_price),
            "Скидка сумма": float(item.qty * item.unit_price * (item.discount_percent or 0) / 100),
            "Скидка %": float(item.discount_percent or 0),
        }
        for item in result.scalars().all()
    ]

    overheads_stmt = select(OverheadExpense)
    if date_from:
        overheads_stmt = overheads_stmt.where(OverheadExpense.created_at >= _period_datetime(date_from, time.min))
    if date_to:
        overheads_stmt = overheads_stmt.where(OverheadExpense.created_at <= _period_datetime(date_to, time.max))
    result = await session.execute(overheads_stmt)
    overheads_rows = [
        {"ID": item.id, "Категория": display_label(item.category), "Сумма": float(item.amount), "Дата": item.created_at}
        for item in result.scalars().all()
    ]

    payroll_result = await session.execute(
        select(PayrollEntry, User).join(User, User.id == PayrollEntry.employee_id)
    )
    payroll_rows = [
        {
            "Сотрудник": user.full_name or user.username,
            "Период": entry.period,
            "Вид работы": entry.work_type,
            "Выработка": float(entry.quantity),
            "Ставка": float(entry.rate),
            "Бонус": float(entry.bonus_amount),
            "Итого": float(entry.total_amount),
        }
        for entry, user in payroll_result
    ]
    penalties_result = await session.execute(
        select(PayrollPenalty, User).join(User, User.id == PayrollPenalty.employee_id)
    )
    penalties_rows = [
        {
            "Сотрудник": user.full_name or user.username,
            "Период": penalty.period,
            "Сумма штрафа": float(penalty.amount),
            "Комментарий": penalty.comment,
            "Дата": penalty.created_at,
        }
        for penalty, user in penalties_result
    ]
    summary = await build_pnl_summary(
        session,
        _period_datetime(date_from, time.min) if date_from else None,
        _period_datetime(date_to, time.max) if date_to else None,
    )
    company_summary = [{
        "Выручка": float(summary["revenue"]),
        "Себестоимость": float(summary["cogs"]),
        "Накладные расходы": float(summary["overheads"]),
        "Зарплата": float(summary["payroll"]),
        "Штрафы": float(summary["penalties"]),
        "Зарплата к выплате": float(summary["net_payroll"]),
        "Приходы денег": float(summary["cash_income"]),
        "Расходы денег": float(summary["cash_expenses"]),
        "Общий счет компании": float(summary["company_balance"]),
        "Прибыль": float(summary["profit"]),
    }]
    return {
        "Продажи": _excel_safe_rows(sales_rows),
        "Состав продаж": sale_items_rows,
        "Накладные расходы": _excel_safe_rows(overheads_rows),
        "Зарплата": payroll_rows,
        "Штрафы": _excel_safe_rows(penalties_rows),
        "Общий счет": company_summary,
    }


@router.get("/pnl")
async def pnl_summary(
    date_from: date | None = None,
    date_to: date | None = None,
    session: AsyncSession = session_dependency,
) -> dict[str, Any]:
    if isinstance(date_from, AsyncSession):
        session = date_from
        date_from = None
    summary = await build_pnl_summary(
        session,
        _period_datetime(date_from, time.min) if date_from else None,
        _period_datetime(date_to, time.max) if date_to else None,
    )
    return {k: str(v) for k, v in summary.items()}


@router.get("/export_excel")
async def export_excel(
    date_from: date | None = None,
    date_to: date | None = None,
    session: AsyncSession = session_dependency,
) -> Response:
    sections = await build_report_sections(session, date_from, date_to)

    # Build Excel with pandas (import lazily to avoid hard dependency at import time)
    try:
        import pandas as pd
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"pandas not available: {e}") from e

    with BytesIO() as buf:
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            for sheet_name, rows in sections.items():
                pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)
        buf.seek(0)
        headers = {"Content-Disposition": "attachment; filename=erp_report.xlsx"}
        return Response(
            content=buf.read(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )


@router.post("/google-sheets/sync")
async def sync_google_sheets(
    date_from: date | None = None,
    date_to: date | None = None,
    session: AsyncSession = session_dependency,
) -> dict[str, Any]:
    sections = await build_report_sections(session, date_from, date_to)
    return await sync_report_sections(sections)
