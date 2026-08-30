from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.schema import Base, Batch, Item, ItemType, PaymentMethod, Warehouse, WarehouseType
from app.api.inventory_api import UpdateBatchPricesRequest, update_batch_prices
from app.services.sales import checkout_sale
from app.services.warehouse_ops import add_stock, move_stock


@pytest.mark.asyncio
async def test_incoming_without_sale_price_keeps_item_price():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        item = Item(code="PRICE-1", name="Priced", type=ItemType.FINAL, unit="pcs", price=Decimal("10"))
        warehouse = Warehouse(id=1, name="Warehouse", description="test")
        session.add_all([item, warehouse])
        await session.flush()
        batch = await add_stock(session, item.id, warehouse.id, Decimal("5"), Decimal("17.50"))
        await session.refresh(item)
        assert item.price == Decimal("10.0000")
        assert batch.purchase_cost == Decimal("17.5000")
        assert batch.sale_price == Decimal("0.0000")
    await engine.dispose()


@pytest.mark.asyncio
async def test_incoming_preserves_explicit_batch_sale_price():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        item = Item(code="PRICE-EXPLICIT", name="Priced", type=ItemType.FINAL, unit="pcs", price=Decimal("100"))
        warehouse = Warehouse(id=1, name="Warehouse", description="test")
        session.add_all([item, warehouse])
        await session.flush()
        batch = await add_stock(
            session, item.id, warehouse.id, Decimal("5"), Decimal("17.50"), sale_price=Decimal("29.00")
        )
        await session.refresh(item)
        assert item.price == Decimal("100.0000")
        assert batch.purchase_cost == Decimal("17.5000")
        assert batch.sale_price == Decimal("29.0000")
    await engine.dispose()


@pytest.mark.asyncio
async def test_batch_sale_price_can_change_without_changing_purchase_cost():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        item = Item(code="PRICE-BATCH-UPDATE", name="Updated Batch", type=ItemType.FINAL, unit="pcs", price=Decimal("100"))
        warehouse = Warehouse(id=1, name="Warehouse", description="test")
        session.add_all([item, warehouse])
        await session.flush()
        batch = await add_stock(session, item.id, warehouse.id, Decimal("5"), Decimal("17.50"), sale_price=Decimal("29.00"))
        updated = await update_batch_prices(
            batch.id,
            UpdateBatchPricesRequest(purchase_cost=Decimal("99.00"), sale_price=Decimal("31.00")),
            session,
        )
        assert updated.purchase_cost == "17.5000"
        assert updated.sale_price == "31.0000"
        assert (await session.get(Batch, batch.id)).purchase_cost == Decimal("17.5000")
        assert (await session.get(Batch, batch.id)).sale_price == Decimal("31.0000")
    await engine.dispose()


@pytest.mark.asyncio
async def test_incoming_without_sale_price_does_not_copy_cost_to_sale_price():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        item = Item(code="PRICE-INDEPENDENT", name="Priced", type=ItemType.FINAL, unit="pcs")
        warehouse = Warehouse(id=1, name="Warehouse", description="test")
        session.add_all([item, warehouse])
        await session.flush()
        batch = await add_stock(session, item.id, warehouse.id, Decimal("5"), Decimal("17.50"))
        assert batch.purchase_cost == Decimal("17.5000")
        assert batch.sale_price == Decimal("0.0000")
    await engine.dispose()


@pytest.mark.asyncio
async def test_incoming_requires_explicit_purchase_cost():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        item = Item(code="PRICE-COST-REQ", name="Cost Required", type=ItemType.FINAL, unit="pcs")
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="Warehouse", description="test")
        session.add_all([item, warehouse])
        await session.flush()
        with pytest.raises(ValueError, match="Себестоимость|purchase cost|Cost"):
            await add_stock(session, item.id, warehouse.id, Decimal("5"), Decimal("0"), sale_price=Decimal("29.00"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_sale_uses_batch_purchase_cost_not_sale_price():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        item = Item(code="PRICE-SALE-COST", name="SaleCost", type=ItemType.FINAL, unit="pcs")
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="Warehouse", description="test")
        batch = Batch(
            item=item,
            warehouse=warehouse,
            purchase_cost=Decimal("17.50"),
            sale_price=Decimal("29.00"),
            initial_qty=Decimal("10"),
            remaining_qty=Decimal("10"),
        )
        session.add_all([item, warehouse, batch])
        await session.flush()
        result = await checkout_sale(
            session,
            counterparty_id=None,
            items=[{"item_id": item.id, "qty": Decimal("2"), "discount_percent": 0}],
            paid_amount=Decimal("58.00"),
            payment_method=PaymentMethod.CASH,
        )
        assert result["total_amount"] == Decimal("58.00")
        sale_item = (await session.execute(__import__('sqlalchemy').select(__import__('sqlalchemy').func.count()).select_from(__import__('sqlalchemy').table('sale_items'))))
        assert result["items"][0]["cost_price"] == Decimal("17.50")
    await engine.dispose()


@pytest.mark.asyncio
async def test_move_uses_manual_or_item_price_for_destination_batch():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        item = Item(code="PRICE-2", name="Moved", type=ItemType.FINAL, unit="pcs", price=Decimal("11"))
        source = Warehouse(id=1, name="Source", description="test")
        target = Warehouse(id=2, name="Target", description="test")
        session.add_all([item, source, target])
        await session.flush()
        await add_stock(session, item.id, source.id, Decimal("4"), Decimal("9"))
        result = await move_stock(session, item.id, source.id, target.id, Decimal("2"), cost=Decimal("13"))
        assert result["destination_batch_id"] > 0
        batch = await session.get(Batch, result["destination_batch_id"])
        assert batch.purchase_cost == Decimal("13.0000")
    await engine.dispose()
