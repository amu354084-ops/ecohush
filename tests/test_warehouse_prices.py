from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.schema import Base, Batch, Item, ItemType, Warehouse
from app.services.warehouse_ops import add_stock, move_stock


@pytest.mark.asyncio
async def test_incoming_updates_item_price():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        item = Item(code="PRICE-1", name="Priced", type=ItemType.FINAL, unit="pcs", price=Decimal("10"))
        warehouse = Warehouse(id=1, name="Warehouse", description="test")
        session.add_all([item, warehouse])
        await session.flush()
        await add_stock(session, item.id, warehouse.id, Decimal("5"), Decimal("17.50"))
        await session.refresh(item)
        assert item.price == Decimal("17.5000")
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
        assert batch.purchase_cost == Decimal("17.5000")
        assert batch.sale_price == Decimal("29.0000")
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
