import pytest
from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.models.schema import Base, CashTransaction, Counterparty, Item, ItemType, PaymentMethod, Sale, SaleItemBatchAllocation, Warehouse, WarehouseType
from app.services.inventory import create_batch
from app.services.sales import checkout_sale, repay_client_debt


async def _setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, AsyncSessionLocal


@pytest.mark.asyncio
async def test_checkout_sale_reduces_batch():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        item = Item(code="S1", name="Sale Item", type=ItemType.FINAL, unit="pcs", min_stock=0)
        # create warehouse with fixed id matching FINISHED warehouse type
        wh = Warehouse(id=WarehouseType.FINISHED, name="WH", description="test")
        session.add_all([item, wh])
        await session.flush()

        batch = await create_batch(
            session=session,
            item_id=item.id,
            warehouse_id=wh.id,
            purchase_cost=Decimal("2.00"),
            qty=Decimal("5"),
        )

        result = await checkout_sale(
            session=session,
            counterparty_id=None,
            items=[
                {
                    "item_id": item.id,
                    "qty": Decimal("2"),
                    "unit_price": Decimal("10.00"),
                }
            ],
            paid_amount=Decimal("20.00"),
            payment_method=PaymentMethod.CASH,
        )

        assert result["total_amount"] == Decimal("20.00")
        # refresh batch and verify remaining
        await session.refresh(batch)
        assert batch.remaining_qty == Decimal("3.00")

    await engine.dispose()


@pytest.mark.asyncio
async def test_checkout_sale_applies_discount_percent():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        item = Item(code="S2", name="Discounted Item", type=ItemType.FINAL, unit="pcs", min_stock=0)
        wh = Warehouse(id=WarehouseType.FINISHED, name="WH2", description="test")
        session.add_all([item, wh])
        await session.flush()

        await create_batch(
            session=session,
            item_id=item.id,
            warehouse_id=wh.id,
            purchase_cost=Decimal("2.00"),
            qty=Decimal("5"),
        )

        result = await checkout_sale(
            session=session,
            counterparty_id=None,
            items=[
                {
                    "item_id": item.id,
                    "qty": Decimal("2"),
                    "unit_price": Decimal("10.00"),
                    "discount_percent": Decimal("10"),
                }
            ],
            paid_amount=Decimal("0"),
            payment_method=PaymentMethod.CASH,
        )

        assert result["total_amount"] == Decimal("18.00")

    await engine.dispose()


@pytest.mark.asyncio
async def test_checkout_sale_rejects_insufficient_stock():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        item = Item(code="S3", name="Limited Item", type=ItemType.FINAL, unit="pcs", min_stock=0)
        wh = Warehouse(id=WarehouseType.FINISHED, name="WH3", description="test")
        session.add_all([item, wh])
        await session.flush()
        await create_batch(
            session=session,
            item_id=item.id,
            warehouse_id=wh.id,
            purchase_cost=Decimal("2.00"),
            qty=Decimal("1"),
        )

        with pytest.raises(ValueError, match="Not enough FIFO stock"):
            await checkout_sale(
                session=session,
                counterparty_id=None,
                items=[{"item_id": item.id, "qty": Decimal("2"), "unit_price": Decimal("10")}],
                paid_amount=Decimal("0"),
                payment_method=PaymentMethod.CASH,
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_checkout_sale_rejects_overpayment():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        item = Item(code="S4", name="Overpayment Item", type=ItemType.FINAL, unit="pcs", min_stock=0)
        wh = Warehouse(id=WarehouseType.FINISHED, name="WH4", description="test")
        session.add_all([item, wh])
        await session.flush()
        batch = await create_batch(session, item.id, wh.id, Decimal("2"), Decimal("1"))
        await session.commit()

        with pytest.raises(ValueError, match="cannot exceed sale total"):
            await checkout_sale(
                session=session,
                counterparty_id=None,
                items=[{"item_id": item.id, "qty": Decimal("1"), "unit_price": Decimal("10")}],
                paid_amount=Decimal("11"),
                payment_method=PaymentMethod.CASH,
            )

        await session.rollback()
        await session.refresh(batch)
        assert batch.remaining_qty == Decimal("1.0000")
    await engine.dispose()


@pytest.mark.asyncio
async def test_repay_client_debt_allocates_oldest_sales_and_updates_balance():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        client = Counterparty(name="Debt Client", current_debt=Decimal("50.00"))
        session.add(client)
        await session.flush()
        first = Sale(
            counterparty_id=client.id,
            total_amount=Decimal("30.00"),
            paid_amount=Decimal("0.00"),
            debt_amount=Decimal("30.00"),
        )
        second = Sale(
            counterparty_id=client.id,
            total_amount=Decimal("20.00"),
            paid_amount=Decimal("0.00"),
            debt_amount=Decimal("20.00"),
        )
        session.add_all([first, second])
        await session.flush()

        result = await repay_client_debt(
            session, client.id, Decimal("40.00"), PaymentMethod.CASH
        )
        await session.commit()

        await session.refresh(first)
        await session.refresh(second)
        await session.refresh(client)
        assert first.debt_amount == Decimal("0.00")
        assert second.debt_amount == Decimal("10.00")
        assert first.paid_amount == Decimal("30.00")
        assert second.paid_amount == Decimal("10.00")
        assert client.current_debt == Decimal("10.00")
        assert result["remaining_debt"] == Decimal("10.00")
        payment_count = await session.scalar(
            select(func.count()).select_from(CashTransaction).where(CashTransaction.counterparty_id == client.id)
        )
        assert payment_count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_checkout_sale_records_all_fifo_batch_allocations():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        item = Item(code="FIFO-AUDIT", name="FIFO Audit", type=ItemType.FINAL, unit="pcs", min_stock=0)
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="FIFO Warehouse", description="test")
        session.add_all([item, warehouse])
        await session.flush()
        first = await create_batch(session, item.id, warehouse.id, Decimal("10"), Decimal("2"))
        second = await create_batch(session, item.id, warehouse.id, Decimal("20"), Decimal("3"))
        result = await checkout_sale(
            session, None,
            [{"item_id": item.id, "qty": Decimal("4"), "unit_price": Decimal("30")}],
            Decimal("120"), PaymentMethod.CASH,
        )
        allocations = (await session.execute(
            select(SaleItemBatchAllocation).order_by(SaleItemBatchAllocation.id)
        )).scalars().all()
        assert result["sale_id"] > 0
        assert [(allocation.batch_id, allocation.qty, allocation.unit_cost) for allocation in allocations] == [
            (first.id, Decimal("2.0000"), Decimal("10.0000")),
            (second.id, Decimal("2.0000"), Decimal("20.0000")),
        ]

    await engine.dispose()
