import pytest
from decimal import Decimal

from app.models.schema import (
    CashTransaction,
    CashTransactionType,
    OverheadExpense,
    PayrollEntry,
    PayrollPenalty,
    Sale,
    SaleItem,
    User,
)
from app.services.reports import build_pnl_summary


@pytest.mark.asyncio
async def test_pnl_rows(session):
    sale = Sale(total_amount=Decimal("200.00"), paid_amount=Decimal("200.00"), debt_amount=Decimal("0.00"))
    sale_item = SaleItem(
        sale=sale,
        item_id=1,
        batch_id=1,
        qty=Decimal("2.00"),
        unit_price=Decimal("100.00"),
        cost_price=Decimal("40.00"),
    )
    overhead = OverheadExpense(category="Test", amount=Decimal("50.00"))
    cash = CashTransaction(type=CashTransactionType.INCOME, amount=Decimal("200.00"), payment_method="CASH")

    session.add_all([sale, sale_item, overhead, cash])
    await session.commit()

    summary = await build_pnl_summary(session)
    assert summary["revenue"] == Decimal("200.00")
    assert summary["cogs"] == Decimal("80.00")
    assert summary["overheads"] == Decimal("50.00")
    assert summary["profit"] == Decimal("70.00")


@pytest.mark.asyncio
async def test_pnl_separates_accrual_profit_from_cash_balance(session):
    employee = User(username="employee", password_hash="hash", role="WORKER")
    session.add(employee)
    await session.flush()
    sale = Sale(total_amount=Decimal("100.00"), paid_amount=Decimal("60.00"), debt_amount=Decimal("40.00"))
    sale_item = SaleItem(
        sale=sale, item_id=1, batch_id=1, qty=Decimal("2"),
        unit_price=Decimal("50"), cost_price=Decimal("20"),
    )
    session.add_all([
        sale,
        sale_item,
        OverheadExpense(category="Rent", amount=Decimal("10")),
        PayrollEntry(
            employee_id=employee.id, period="2026-08", work_type="shift",
            quantity=Decimal("5"), rate=Decimal("10"), bonus_amount=Decimal("0"),
            total_amount=Decimal("50"),
        ),
        PayrollPenalty(employee_id=employee.id, period="2026-08", amount=Decimal("5"), comment="Late"),
        CashTransaction(type=CashTransactionType.INCOME, amount=Decimal("60"), payment_method="CASH"),
        CashTransaction(type=CashTransactionType.EXPENSE, amount=Decimal("7"), payment_method="CASH"),
    ])
    await session.commit()

    summary = await build_pnl_summary(session)

    assert summary["net_payroll"] == Decimal("45.00")
    assert summary["profit"] == Decimal("5.00")
    assert summary["cash_income"] == Decimal("60.00")
    assert summary["cash_expenses"] == Decimal("7.00")
    assert summary["company_balance"] == Decimal("53.00")
