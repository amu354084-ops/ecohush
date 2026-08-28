import pytest
from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.models.schema import (
    Base,
    Batch,
    BOMHeader,
    BOMItem,
    Item,
    ItemType,
    ProductionOrderStatus,
    StockTransaction,
    Warehouse,
)
from app.services.inventory import create_batch
from app.services.production import complete_production_order, create_production_order, execute_production


async def _setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, AsyncSessionLocal


@pytest.mark.asyncio
async def test_execute_production_creates_finished_batch():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        # create items and warehouse
        comp = Item(code="C1", name="Component", type=ItemType.RAW, unit="pcs", min_stock=0)
        product = Item(code="P1", name="Product", type=ItemType.FINAL, unit="pcs", min_stock=0)
        wh = Warehouse(name="RAW", description="raw wh")
        wh_fin = Warehouse(name="FIN", description="finished wh")
        session.add_all([comp, product, wh, wh_fin])
        await session.flush()

        # BOM: product uses 2 units of component
        bom = BOMHeader(product_id=product.id, name="BOM1", is_active=True)
        session.add(bom)
        await session.flush()
        bom_item = BOMItem(bom_id=bom.id, component_id=comp.id, quantity=Decimal("2"), scrap_rate_percent=Decimal("0"))
        session.add(bom_item)
        await session.flush()

        # create component batch with enough qty
        await create_batch(
            session=session,
            item_id=comp.id,
            warehouse_id=wh.id,
            purchase_cost=Decimal("1.50"),
            qty=Decimal("10"),
        )

        # execute production for output_qty=2 -> requires 4 units of component
        result = await execute_production(
            session=session,
            bom_id=bom.id,
            output_qty=Decimal("2"),
            additional_overheads=Decimal("0"),
            actual_waste={},
        )

        assert result["product_id"] == product.id
        assert result["output_qty"] == Decimal("2")
        # unit cost should be numeric
        assert Decimal(result["unit_cost"]) >= 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_execute_production_rejects_missing_bom(session):
    with pytest.raises(ValueError, match="Active BOM not found"):
        await execute_production(
            session=session,
            bom_id=999999,
            output_qty=Decimal("1"),
            additional_overheads=Decimal("0"),
            actual_waste={},
        )


@pytest.mark.asyncio
async def test_production_order_lifecycle_deducts_raw_and_receives_finished():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        raw = Item(code="RAW-ORDER", name="Raw material", type=ItemType.RAW, unit="kg", min_stock=0)
        product = Item(code="FINAL-ORDER", name="Finished product", type=ItemType.FINAL, unit="kg", min_stock=0)
        raw_warehouse = Warehouse(name="Raw warehouse", description="")
        finished_warehouse = Warehouse(name="Finished warehouse", description="")
        session.add_all([raw, product, raw_warehouse, finished_warehouse])
        await session.flush()
        bom = BOMHeader(product_id=product.id, name="Order BOM", is_active=True)
        session.add(bom)
        await session.flush()
        session.add(BOMItem(bom_id=bom.id, component_id=raw.id, quantity=Decimal("2"), scrap_rate_percent=Decimal("10")))
        await create_batch(session, raw.id, raw_warehouse.id, Decimal("3"), Decimal("10"))
        order = await create_production_order(session, "BATCH-001", bom.id, Decimal("1"))

        result = await complete_production_order(session, order.id, Decimal("1"))

        assert result["actual_qty"] == Decimal("1")
        assert result["unit_cost"] == Decimal("6.6000")
        saved_order = await session.get(type(order), order.id)
        assert saved_order.status == ProductionOrderStatus.COMPLETED
        raw_batch = await session.scalar(select(Batch).where(Batch.item_id == raw.id))
        assert raw_batch.remaining_qty == Decimal("7.8")
        output_batch = await session.scalar(select(Batch).where(Batch.item_id == product.id))
        assert output_batch.remaining_qty == Decimal("1")
        transaction_count = await session.scalar(select(func.count(StockTransaction.id)))
        assert transaction_count == 2
    await engine.dispose()
