from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.models.schema import Base, Item, ItemType, Warehouse
from app.services.inventory import create_batch, deduct_fifo


async def _setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, AsyncSessionLocal


@pytest.mark.asyncio
async def test_deduct_fifo_basic():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        # create item and warehouse
        item = Item(
            code="TST1",
            name="Test Item",
            type=ItemType.RAW,
            unit="pcs",
            min_stock=0,
        )
        warehouse = Warehouse(name="WH1", description="Test")
        session.add_all([item, warehouse])
        await session.flush()

        # create batch
        batch = await create_batch(
            session=session,
            item_id=item.id,
            warehouse_id=warehouse.id,
            purchase_cost=Decimal("5.00"),
            qty=Decimal("10"),
        )

        total_cost, moves = await deduct_fifo(
            session=session,
            item_id=item.id,
            required_qty=Decimal("3"),
            target_warehouse_id=warehouse.id,
        )

        assert total_cost == Decimal("15.00")
        assert len(moves) == 1
        assert moves[0]["qty"] == Decimal("3")
        # refresh batch
        await session.refresh(batch)
        assert batch.remaining_qty == Decimal("7")

    await engine.dispose()
