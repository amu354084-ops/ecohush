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
    Order,
    OrderItem,
    OverheadExpense,
    PaymentMethod,
    Sale,
    SaleItem,
    User,
    Warehouse,
    WarehouseType,
)
from app.services.dashboard import build_dashboard_summary
from app.api.dashboard_api import seller_performance
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
        session.add_all([warehouse, item, batch, low_stock_item, low_stock_batch, sale, sale_item, expense])
        await session.commit()

        summary = await build_dashboard_summary(session)

        assert summary["sales_count"] == 1
        assert summary["income"] == Decimal("100.00")
        assert summary["cogs"] == Decimal("40.00")
        assert summary["expense"] == Decimal("0.00")
        assert summary["profit"] == Decimal("60.00")
        assert summary["profit"] == summary["revenue"] - summary["cogs"] - summary["operating_expenses"]
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


@pytest.mark.asyncio
async def test_dashboard_period_filters_recent_sales_and_top_clients():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        in_range_client = Counterparty(name="In range", phone="1")
        old_client = Counterparty(name="Old", phone="2")
        in_range_sale = Sale(
            counterparty=in_range_client,
            total_amount=Decimal("100"),
            paid_amount=Decimal("100"),
            debt_amount=Decimal("0"),
            created_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        )
        old_sale = Sale(
            counterparty=old_client,
            total_amount=Decimal("900"),
            paid_amount=Decimal("900"),
            debt_amount=Decimal("0"),
            created_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        )
        session.add_all([in_range_client, old_client, in_range_sale, old_sale])
        await session.commit()

        summary = await build_dashboard_summary(
            session,
            date_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
            date_to=datetime(2026, 8, 31, 23, 59, 59, tzinfo=timezone.utc),
        )

        assert [sale["sale_id"] for sale in summary["recent_sales"]] == [in_range_sale.id]
        assert [client["client_name"] for client in summary["top_clients"]] == ["In range"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_tracks_seller_sales_referrers_and_note_expenses():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        seller = User(username="seller1", password_hash="hash", full_name="Seller One", role="COURIER")
        client = Counterparty(name="Client A", phone="111")
        session.add_all([seller, client])
        await session.flush()

        sale_one = Sale(
            counterparty=client,
            total_amount=Decimal("200.00"),
            paid_amount=Decimal("200.00"),
            debt_amount=Decimal("0.00"),
            created_at=datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc),
        )
        sale_two = Sale(
            counterparty=client,
            total_amount=Decimal("50.00"),
            paid_amount=Decimal("50.00"),
            debt_amount=Decimal("0.00"),
            created_at=datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc),
        )
        session.add_all([sale_one, sale_two])
        await session.flush()

        session.add_all([
            Order(courier_id=seller.id, client_id=client.id, sale_id=sale_one.id, referred_by="Ali", status="DELIVERED"),
            Order(courier_id=seller.id, client_id=client.id, sale_id=sale_two.id, referred_by="Ali", status="DELIVERED"),
            CashTransaction(
                type=CashTransactionType.EXPENSE,
                amount=Decimal("30.00"),
                payment_method=PaymentMethod.CASH,
                description="Rent",
                is_company_expense=True,
            ),
            CashTransaction(
                type=CashTransactionType.EXPENSE,
                amount=Decimal("40.00"),
                payment_method=PaymentMethod.CASH,
                description="Taxi note",
                is_company_expense=False,
            ),
        ])
        await session.commit()

        summary = await build_dashboard_summary(session)

        assert summary["sales_by_seller"][0] == {
            "seller_id": seller.id,
            "seller_name": "Seller One",
            "sales_count": 2,
            "total_amount": Decimal("250.00"),
        }
        assert summary["top_referrers"][0] == {
            "referrer_name": "Ali",
            "sales_count": 2,
            "total_amount": Decimal("250.00"),
        }
        assert summary["note_expenses"] == Decimal("40.00")
        assert summary["cash_expenses"] == Decimal("30.00")
        assert summary["company_balance"] == Decimal("-30.00")

    await engine.dispose()


@pytest.mark.asyncio
async def test_seller_performance_groups_sales_by_employee_referrer_and_lists_products():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        seller = User(username="seller-report", password_hash="hash", full_name="Seller Report", role="COURIER")
        referrer = User(username="referrer-report", password_hash="hash", full_name="Referrer Report", role="AGENT")
        client = Counterparty(name="Seller Report Client")
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="Finished", description="test")
        item = Item(code="SELLER-REPORT-1", name="Report Product", type=ItemType.FINAL, unit="pcs", min_stock=0)
        batch = Batch(item=item, warehouse=warehouse, purchase_cost=Decimal("4.00"), initial_qty=Decimal("5"), remaining_qty=Decimal("5"))
        sale = Sale(counterparty=client, total_amount=Decimal("24.00"), paid_amount=Decimal("24.00"), debt_amount=Decimal("0.00"))
        order = Order(
            courier=seller,
            client=client,
            sale_id=1,
            referred_by=referrer.full_name,
            referred_by_user_id=1,
            status="DELIVERED",
            invoice_number="20260930-9001",
        )
        order_item = OrderItem(order=order, item=item, quantity=Decimal("3"), price=Decimal("8.00"), discount=Decimal("0.00"))
        sale_item = SaleItem(sale=sale, item=item, batch=batch, qty=Decimal("3"), unit_price=Decimal("8.00"), cost_price=Decimal("4.00"))
        session.add_all([seller, referrer, client, warehouse, item, batch, sale, order, order_item, sale_item])
        await session.flush()
        order.sale_id = sale.id
        order.referred_by_user_id = referrer.id
        await session.flush()

        report = await seller_performance(seller.id, None, None, session)

        assert report["seller_name"] == "Seller Report"
        assert report["total_amount"] == Decimal("24.00")
        assert report["sales_count"] == 1
        assert report["by_referrer"][0]["referrer_name"] == "Referrer Report"
        assert report["by_referrer"][0]["total_amount"] == Decimal("24.00")
        assert report["orders"][0]["items"] == "Report Product × 3 pcs"

    await engine.dispose()


@pytest.mark.asyncio
async def test_seller_performance_includes_legacy_delivered_order_without_sale_link():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        seller = User(username="legacy-seller-report", password_hash="hash", full_name="Legacy Seller", role="COURIER")
        client = Counterparty(name="Legacy Report Client")
        item = Item(code="LEGACY-SELLER-1", name="Legacy Product", type=ItemType.FINAL, unit="pcs", min_stock=0)
        order = Order(
            courier=seller,
            client=client,
            status="DELIVERED",
            delivered_at=datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc),
        )
        order_item = OrderItem(
            order=order,
            item=item,
            quantity=Decimal("10"),
            price=Decimal("195"),
            discount=Decimal("0"),
        )
        session.add_all([seller, client, item, order, order_item])
        await session.flush()

        report = await seller_performance(seller.id, None, None, session)

        assert report["total_amount"] == Decimal("1950.00")
        assert report["sales_count"] == 1
        assert report["orders"][0]["order_id"] == order.id
        assert report["orders"][0]["items"] == "Legacy Product × 10 pcs"

    await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_daily_values_use_application_timezone():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        sale = Sale(
            total_amount=Decimal("100"),
            paid_amount=Decimal("100"),
            debt_amount=Decimal("0"),
            created_at=datetime(2026, 8, 1, 22, 30, tzinfo=timezone.utc),
        )
        session.add(sale)
        await session.commit()

        summary = await build_dashboard_summary(
            session,
            date_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
            date_to=datetime(2026, 8, 2, 23, 59, 59, tzinfo=timezone.utc),
        )

        daily = {row["day"]: row["income"] for row in summary["daily_sales"]}
        assert daily["2026-08-02"] == Decimal("100.00")

    await engine.dispose()
