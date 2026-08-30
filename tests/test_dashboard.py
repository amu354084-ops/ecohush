import pytest
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.schema import (
    Base,
    Batch,
    CashTransaction,
    CashTransactionType,
    Counterparty,
    Item,
    ItemType,
    OverheadExpense,
    PaymentMethod,
    Sale,
    SaleItem,
    Warehouse,
    WarehouseType,
)
from app.services.dashboard import build_dashboard_summary
from app.services.timezone import get_app_timezone


def test_app_timezone_is_dushanbe():
    assert get_app_timezone().key == "Asia/Dushanbe"


async def _setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, AsyncSessionLocal


@pytest.mark.asyncio
async def test_build_dashboard_summary_counts_sales_and_finance():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="WH", description="test")
        item = Item(code="D1", name="Demo", type=ItemType.FINAL, unit="pcs", min_stock=3)
        batch = Batch(
            item=item,
            warehouse=warehouse,
            purchase_cost=Decimal("20.00"),
            initial_qty=Decimal("10.00"),
            remaining_qty=Decimal("10.00"),
        )
        low_stock_item = Item(code="D2", name="Low Stock", type=ItemType.FINAL, unit="pcs", min_stock=3)
        low_stock_batch = Batch(
            item=low_stock_item,
            warehouse=warehouse,
            purchase_cost=Decimal("15.00"),
            initial_qty=Decimal("2.00"),
            remaining_qty=Decimal("2.00"),
        )
        sale = Sale(
            counterparty_id=None,
            total_amount=Decimal("100.00"),
            paid_amount=Decimal("100.00"),
            debt_amount=Decimal("0.00"),
            created_at=datetime.now(timezone.utc),
        )
        sale_item = SaleItem(
            sale=sale,
            item=item,
            batch=batch,
            qty=Decimal("2.00"),
            unit_price=Decimal("50.00"),
            cost_price=Decimal("20.00"),
        )
        expense = CashTransaction(
            type=CashTransactionType.EXPENSE,
            amount=Decimal("30.00"),
            payment_method=PaymentMethod.BANK,
            description="rent",
        )
        overhead = None
        session.add_all([warehouse, item, batch, low_stock_item, low_stock_batch, sale, sale_item, expense])
        await session.commit()

        summary = await build_dashboard_summary(session)

        assert summary["sales_count"] == 1
        assert summary["income"] == Decimal("100.00")
        assert summary["cogs"] == Decimal("40.00")
        assert summary["expense"] == Decimal("0.00")
        assert summary["profit"] == Decimal("60.00")
        chart_total = sum((entry["value"] for entry in summary["chart"]["values"]), Decimal("0.00"))
        assert chart_total == summary["revenue"]
        assert summary["cash_income"] == Decimal("0.00")
        assert summary["cash_expenses"] == Decimal("30.00")
        assert summary["company_balance"] == Decimal("-30.00")
        assert summary["total_stock_qty"] == Decimal("12.00")
        assert summary["low_stock_items"] == 1
        assert summary["low_stock_details"] == [{
            "item_id": low_stock_item.id,
            "code": "D2",
            "name": "Low Stock",
            "unit": "pcs",
            "remaining_qty": "2.00",
            "min_stock": "3",
        }]
        assert any(row["income"] == Decimal("100.00") for row in summary["daily_sales"])
        assert summary["recent_sales"][0]["total_amount"] == Decimal("100.00")
        assert summary["recent_sales"][0]["paid_amount"] == Decimal("100.00")
        assert summary["daily_finance"]
        assert any(row["income"] == Decimal("100.00") for row in summary["daily_finance"])
        assert any(row["expense"] == Decimal("40.00") for row in summary["daily_finance"])

    await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_chart_keeps_strict_financial_formula_for_negative_profit():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="WH", description="test")
        item = Item(code="D4", name="Loss Item", type=ItemType.FINAL, unit="pcs", min_stock=0)
        batch = Batch(
            item=item,
            warehouse=warehouse,
            purchase_cost=Decimal("40.00"),
            initial_qty=Decimal("10.00"),
            remaining_qty=Decimal("10.00"),
        )
        sale = Sale(
            counterparty_id=None,
            total_amount=Decimal("100.00"),
            paid_amount=Decimal("100.00"),
            debt_amount=Decimal("0.00"),
            created_at=datetime.now(timezone.utc),
        )
        session.add_all([
            warehouse,
            item,
            batch,
            sale,
            SaleItem(
                sale=sale,
                item=item,
                batch=batch,
                qty=Decimal("2.00"),
                unit_price=Decimal("50.00"),
                cost_price=Decimal("40.00"),
            ),
            OverheadExpense(category="rent", amount=Decimal("30.00"), created_at=datetime.now(timezone.utc)),
        ])
        await session.commit()

        summary = await build_dashboard_summary(session)

        assert summary["profit"] == Decimal("-10.00")
        assert summary["cogs"] == Decimal("80.00")
        assert summary["operating_expenses"] == Decimal("30.00")
        assert summary["revenue"] == Decimal("100.00")
        chart_total = sum((entry["value"] for entry in summary["chart"]["values"]), Decimal("0.00"))
        assert chart_total == summary["revenue"]
        assert any(entry["key"] == "net_profit" and entry["value"] < 0 for entry in summary["chart"]["values"])

    await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_daily_summary_respects_selected_period():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="WH", description="test")
        item = Item(code="D3", name="Period Item", type=ItemType.FINAL, unit="pcs", min_stock=0)
        batch = Batch(
            item=item,
            warehouse=warehouse,
            purchase_cost=Decimal("10.00"),
            initial_qty=Decimal("10.00"),
            remaining_qty=Decimal("10.00"),
        )
        in_range_day = datetime(2026, 8, 15, 9, 30, tzinfo=timezone.utc)
        out_of_range_day = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)
        in_range_sale = Sale(
            counterparty_id=None,
            total_amount=Decimal("120.00"),
            paid_amount=Decimal("120.00"),
            debt_amount=Decimal("0.00"),
            created_at=in_range_day,
        )
        out_of_range_sale = Sale(
            counterparty_id=None,
            total_amount=Decimal("50.00"),
            paid_amount=Decimal("50.00"),
            debt_amount=Decimal("0.00"),
            created_at=out_of_range_day,
        )
        session.add_all([
            warehouse,
            item,
            batch,
            in_range_sale,
            out_of_range_sale,
            SaleItem(
                sale=in_range_sale,
                item=item,
                batch=batch,
                qty=Decimal("2.00"),
                unit_price=Decimal("60.00"),
                cost_price=Decimal("10.00"),
            ),
            SaleItem(
                sale=out_of_range_sale,
                item=item,
                batch=batch,
                qty=Decimal("1.00"),
                unit_price=Decimal("50.00"),
                cost_price=Decimal("10.00"),
            ),
        ])
        await session.commit()

        summary = await build_dashboard_summary(
            session,
            date_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
            date_to=datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc),
        )

        assert summary["income"] == Decimal("120.00")
        assert not any(row["day"] == out_of_range_day.date().isoformat() and row["income"] != Decimal("0.00") for row in summary["daily_sales"])
        assert any(row["day"] == in_range_day.date().isoformat() and row["income"] == Decimal("120.00") for row in summary["daily_sales"])

    await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_top_clients_uses_all_sale_totals():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        first_client = Counterparty(name="Top Client", phone="100")
        second_client = Counterparty(name="Second Client", phone="200")
        session.add_all([
            first_client,
            second_client,
            Sale(counterparty=first_client, total_amount=Decimal("300"), paid_amount=Decimal("100"), debt_amount=Decimal("200")),
            Sale(counterparty=first_client, total_amount=Decimal("50"), paid_amount=Decimal("50"), debt_amount=Decimal("0")),
            Sale(counterparty=second_client, total_amount=Decimal("200"), paid_amount=Decimal("200"), debt_amount=Decimal("0")),
        ])
        await session.commit()

        summary = await build_dashboard_summary(session)

        assert summary["top_clients"][0] == {
            "client_id": first_client.id,
            "client_name": "Top Client",
            "phone": "100",
            "total_amount": Decimal("350.00"),
            "sales_count": 2,
        }

    await engine.dispose()
