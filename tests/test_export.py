import pytest
from decimal import Decimal

from app.models.schema import CashTransaction, CashTransactionType, OverheadExpense, Sale, SaleItem
from app.api.reports_api import pnl_summary


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
