from __future__ import annotations

from decimal import Decimal
from datetime import date, datetime, time
from io import BytesIO
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import require_section
from app.db import async_session
from app.models.schema import CashTransaction, CashTransactionType, Counterparty, OverheadExpense, PaymentMethod, PayrollEntry, PayrollPenalty, User
from app.api.auth_dependencies import require_roles
from app.services.localization import display_label
from app.services.reports import build_pnl_summary


class OverheadCreateRequest(BaseModel):
    category: str = Field(min_length=1, max_length=128)
    amount: Decimal = Field(gt=0)


class OverheadResponse(BaseModel):
    id: int
    category: str
    amount: str


class CashTransactionCreateRequest(BaseModel):
    type: CashTransactionType
    amount: Decimal = Field(gt=0)
    payment_method: PaymentMethod
    counterparty_id: int | None = None
    description: str = Field(default="", max_length=500)


class CashTransactionResponse(BaseModel):
    id: int
    type: str
    amount: str
    payment_method: str
    counterparty_id: int | None
    counterparty_name: str | None
    description: str | None
    created_at: str


class PayrollCreateRequest(BaseModel):
    employee_id: int = Field(gt=0)
    production_order_id: int | None = Field(default=None, gt=0)
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    work_type: str = Field(min_length=1, max_length=32)
    quantity: Decimal = Field(gt=0)
    rate: Decimal = Field(gt=0)
    bonus_amount: Decimal = Field(default=Decimal(0), ge=0)
    penalty_amount: Decimal = Field(default=Decimal(0), ge=0)
    penalty_comment: str = Field(default="", max_length=500)


class PayrollResponse(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    period: str
    work_type: str
    quantity: str
    rate: str
    bonus_amount: str
    total_amount: str


class PenaltyCreateRequest(BaseModel):
    employee_id: int = Field(gt=0)
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    amount: Decimal = Field(gt=0)
    comment: str = Field(min_length=1, max_length=500)


class PenaltyResponse(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    period: str
    amount: str
    comment: str
    created_at: str


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


session_dependency = Depends(get_session)
router = APIRouter(dependencies=[Depends(require_section("finance"))])


@router.get("/overview")
async def finance_overview(
    date_from: date | None = None,
    date_to: date | None = None,
    session: AsyncSession = session_dependency,
) -> dict[str, str]:
    summary = await build_pnl_summary(
        session,
        datetime.combine(date_from, time.min) if date_from else None,
        datetime.combine(date_to, time.max) if date_to else None,
    )

    return {
        "income": str(summary["revenue"]),
        "revenue": str(summary["revenue"]),
        "cogs": str(summary["cogs"]),
        "cash_income": str(summary["cash_income"]),
        "cash_expenses": str(summary["cash_expenses"]),
        "overheads": str(summary["overheads"]),
        "payroll": str(summary["payroll"]),
        "penalties": str(summary["penalties"]),
        "net_payroll": str(summary["net_payroll"]),
        "profit": str(summary["profit"]),
        "company_balance": str(summary["company_balance"]),
        "net_cash": str(summary["company_balance"]),
    }


@router.get("/transactions", response_model=list[CashTransactionResponse])
async def list_transactions(
    limit: int = 10,
    offset: int = 0,
    date_from: date | None = None,
    date_to: date | None = None,
    session: AsyncSession = session_dependency,
) -> list[CashTransactionResponse]:
    stmt = (
        select(CashTransaction)
        .order_by(CashTransaction.created_at.desc(), CashTransaction.id.desc())
        .limit(max(1, min(limit, 100)))
        .offset(max(0, offset))
    )
    if date_from:
        stmt = stmt.where(CashTransaction.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(CashTransaction.created_at <= datetime.combine(date_to, time.max))
    result = await session.execute(stmt)
    transactions = result.scalars().all()

    rows: list[CashTransactionResponse] = []
    for tx in transactions:
        counterparty_name = None
        if tx.counterparty_id is not None:
            cp = await session.get(Counterparty, tx.counterparty_id)
            counterparty_name = cp.name if cp else None
        rows.append(
            CashTransactionResponse(
                id=tx.id,
                type=display_label(tx.type),
                amount=str(tx.amount),
                payment_method=display_label(tx.payment_method),
                counterparty_id=tx.counterparty_id,
                counterparty_name=counterparty_name,
                description=display_label(tx.description or ""),
                created_at=tx.created_at.isoformat(),
            )
        )
    return rows


@router.get("/overheads", response_model=list[OverheadResponse])
async def list_overheads(
    limit: int = 10,
    offset: int = 0,
    date_from: date | None = None,
    date_to: date | None = None,
    session: AsyncSession = session_dependency,
) -> list[OverheadResponse]:
    stmt = (
        select(OverheadExpense)
        .order_by(OverheadExpense.id.desc())
        .limit(max(1, min(limit, 100)))
        .offset(max(0, offset))
    )
    if date_from:
        stmt = stmt.where(OverheadExpense.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(OverheadExpense.created_at <= datetime.combine(date_to, time.max))
    result = await session.execute(stmt)
    return [
        OverheadResponse(
            id=o.id,
            category=display_label(o.category),
            amount=str(o.amount),
        )
        for o in result.scalars().all()
    ]


@router.post("/overheads", response_model=OverheadResponse)
async def add_overhead(request: OverheadCreateRequest, session: AsyncSession = session_dependency) -> OverheadResponse:
    overhead = OverheadExpense(category=request.category, amount=request.amount)
    session.add(overhead)
    await session.flush()
    return OverheadResponse(id=overhead.id, category=display_label(overhead.category), amount=str(overhead.amount))


@router.post("/transactions", response_model=CashTransactionResponse)
async def add_transaction(
    request: CashTransactionCreateRequest,
    session: AsyncSession = session_dependency,
) -> CashTransactionResponse:
    if request.counterparty_id is not None and await session.get(Counterparty, request.counterparty_id) is None:
        raise ValueError("Контрагент не найден")
    transaction = CashTransaction(
        type=request.type,
        amount=request.amount,
        payment_method=request.payment_method,
        counterparty_id=request.counterparty_id,
        description=request.description.strip() or None,
    )
    session.add(transaction)
    await session.flush()
    await session.commit()
    counterparty = await session.get(Counterparty, transaction.counterparty_id) if transaction.counterparty_id else None
    return CashTransactionResponse(
        id=transaction.id,
        type=display_label(transaction.type),
        amount=str(transaction.amount),
        payment_method=display_label(transaction.payment_method),
        counterparty_id=transaction.counterparty_id,
        counterparty_name=counterparty.name if counterparty else None,
        description=display_label(transaction.description or ""),
        created_at=transaction.created_at.isoformat(),
    )


@router.get("/payroll", response_model=list[PayrollResponse])
async def list_payroll(session: AsyncSession = session_dependency) -> list[PayrollResponse]:
    result = await session.execute(select(PayrollEntry, User).join(User, User.id == PayrollEntry.employee_id).order_by(PayrollEntry.id.desc()))
    return [PayrollResponse(
        id=entry.id, employee_id=entry.employee_id, employee_name=user.full_name or user.username,
        period=entry.period, work_type=entry.work_type, quantity=str(entry.quantity), rate=str(entry.rate),
        bonus_amount=str(entry.bonus_amount), total_amount=str(entry.total_amount),
    ) for entry, user in result]


@router.get("/penalties", response_model=list[PenaltyResponse])
async def list_penalties(q: str | None = None, session: AsyncSession = session_dependency) -> list[PenaltyResponse]:
    stmt = select(PayrollPenalty, User).join(User, User.id == PayrollPenalty.employee_id).order_by(PayrollPenalty.id.desc())
    if q and q.strip():
        search = f"%{q.strip()}%"
        stmt = stmt.where((User.full_name.ilike(search)) | (User.username.ilike(search)) | (PayrollPenalty.comment.ilike(search)))
    result = await session.execute(stmt)
    return [PenaltyResponse(
        id=penalty.id, employee_id=penalty.employee_id, employee_name=user.full_name or user.username,
        period=penalty.period, amount=str(penalty.amount), comment=penalty.comment,
        created_at=penalty.created_at.isoformat(),
    ) for penalty, user in result]


@router.post("/penalties", response_model=PenaltyResponse)
async def add_penalty(request: PenaltyCreateRequest, session: AsyncSession = session_dependency) -> PenaltyResponse:
    employee = await session.get(User, request.employee_id)
    if employee is None or not employee.is_active:
        raise ValueError("Выберите активного сотрудника")
    penalty = PayrollPenalty(
        employee_id=employee.id, period=request.period, amount=request.amount, comment=request.comment.strip()
    )
    session.add(penalty)
    await session.flush()
    await session.commit()
    return PenaltyResponse(
        id=penalty.id, employee_id=penalty.employee_id, employee_name=employee.full_name or employee.username,
        period=penalty.period, amount=str(penalty.amount), comment=penalty.comment,
        created_at=penalty.created_at.isoformat(),
    )


@router.get("/employees")
async def list_payroll_employees(session: AsyncSession = session_dependency) -> list[dict[str, str | int]]:
    users = (await session.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.full_name, User.username)
    )).scalars().all()
    return [{"id": user.id, "name": user.full_name or user.username} for user in users]


@router.post("/payroll", response_model=PayrollResponse)
async def add_payroll(request: PayrollCreateRequest, session: AsyncSession = session_dependency) -> PayrollResponse:
    employee = await session.get(User, request.employee_id)
    if employee is None:
        raise ValueError("Сотрудник не найден")
    if not employee.is_active:
        raise ValueError("Нельзя начислить зарплату неактивному сотруднику")
    total_amount = (request.quantity * request.rate + request.bonus_amount).quantize(Decimal("0.01"))
    entry = PayrollEntry(
        employee_id=request.employee_id, production_order_id=request.production_order_id,
        period=request.period, work_type=request.work_type, quantity=request.quantity,
        rate=request.rate, bonus_amount=request.bonus_amount, total_amount=total_amount,
    )
    session.add(entry)
    if request.penalty_amount > 0:
        if not request.penalty_comment.strip():
            raise ValueError("Укажите комментарий к штрафу")
        session.add(PayrollPenalty(
            employee_id=employee.id, period=request.period,
            amount=request.penalty_amount, comment=request.penalty_comment.strip(),
        ))
    await session.flush()
    await session.commit()
    return PayrollResponse(
        id=entry.id, employee_id=entry.employee_id, employee_name=employee.full_name or employee.username,
        period=entry.period, work_type=entry.work_type, quantity=str(entry.quantity), rate=str(entry.rate),
        bonus_amount=str(entry.bonus_amount), total_amount=str(entry.total_amount),
    )


@router.get("/transactions/export")
async def export_transactions(
    date_from: date | None = None,
    date_to: date | None = None,
    _: User = Depends(require_roles("ADMIN")),
    session: AsyncSession = session_dependency,
):
    import csv
    import io

    transaction_stmt = select(CashTransaction).order_by(
        CashTransaction.created_at.desc(), CashTransaction.id.desc()
    )
    if date_from:
        transaction_stmt = transaction_stmt.where(
            CashTransaction.created_at >= datetime.combine(date_from, time.min)
        )
    if date_to:
        transaction_stmt = transaction_stmt.where(
            CashTransaction.created_at <= datetime.combine(date_to, time.max)
        )
    result = await session.execute(transaction_stmt)
    rows = []
    for transaction in result.scalars().all():
        counterparty = (
            await session.get(Counterparty, transaction.counterparty_id)
            if transaction.counterparty_id
            else None
        )
        rows.append({
            "ID": transaction.id,
            "Операция": display_label(transaction.type),
            "Сумма": str(transaction.amount),
            "Способ оплаты": display_label(transaction.payment_method),
            "Контрагент": counterparty.name if counterparty else "",
            "Комментарий": display_label(transaction.description or ""),
            "Дата": transaction.created_at.isoformat(),
        })
    overhead_stmt = select(OverheadExpense).order_by(OverheadExpense.id.desc())
    if date_from:
        overhead_stmt = overhead_stmt.where(OverheadExpense.created_at >= datetime.combine(date_from, time.min))
    if date_to:
        overhead_stmt = overhead_stmt.where(OverheadExpense.created_at <= datetime.combine(date_to, time.max))
    overhead_result = await session.execute(overhead_stmt)
    overhead_rows = [
        {
            "ID": overhead.id,
            "Категория": display_label(overhead.category),
            "Сумма": str(overhead.amount),
            "Дата": overhead.created_at.isoformat() if overhead.created_at else "",
        }
        for overhead in overhead_result.scalars().all()
    ]
    filename = "finance_report.xlsx"
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    try:
        import pandas as pd

        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="Денежные операции")
            pd.DataFrame(overhead_rows).to_excel(writer, index=False, sheet_name="Накладные расходы")
        data = buffer.getvalue()
    except Exception:
        output = io.StringIO()
        fieldnames = ["ID", "Операция", "Сумма", "Способ оплаты", "Контрагент", "Комментарий", "Дата"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        data = output.getvalue().encode("utf-8-sig")
        filename = "finance_report.csv"
        media_type = "text/csv"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
