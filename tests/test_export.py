import pytest
from datetime import datetime, timezone
from decimal import Decimal

from app.models.schema import CashTransaction, CashTransactionType, OverheadExpense, Sale, SaleItem
from app.api.reports_api import _excel_safe_rows, pnl_summary


def test_excel_safe_rows_removes_datetime_timezone():
    aware_datetime = datetime(2026, 8, 27, 15, 30, tzinfo=timezone.utc)

    rows = _excel_safe_rows([{"Дата": aware_datetime, "Сумма": 10}])

    assert rows == [{"Дата": datetime(2026, 8, 27, 15, 30), "Сумма": 10}]


@pytest.mark.asyncio
async def test_pnl_summary_api(session):
    sale = Sale(
        total_amount=Decimal("150.00"),
        paid_amount=Decimal("150.00"),
        debt_amount=Decimal("0.00"),
    )
    sale_item = SaleItem(
        sale=sale,
        item_id=1,
        batch_id=1,
        qty=Decimal("1.00"),
        unit_price=Decimal("150.00"),
        cost_price=Decimal("50.00"),
    )
    overhead = OverheadExpense(category="Test", amount=Decimal("25.00"))
    cash = CashTransaction(type=CashTransactionType.INCOME, amount=Decimal("150.00"), payment_method="CASH")
    session.add_all([sale, sale_item, overhead, cash])
    await session.commit()

    result = await pnl_summary(session)
    assert result["revenue"] == "150.00"
    assert result["cogs"] == "50.00"
    assert result["overheads"] == "25.00"
    assert result["profit"] == "75.00"
