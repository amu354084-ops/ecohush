import pytest
from decimal import Decimal

from sqlalchemy import select

from app.models.schema import Batch, Item, ItemType, StockTransaction, StockTransactionType, Warehouse, WarehouseType
from app.services.inventory import adjust_stock
from app.services.warehouse_ops import add_stock, move_stock


async def _setup_items(session):
    item = Item(code="ITM2", name="Item 2", type=ItemType.RAW, unit="pcs", min_stock=1)
    warehouse1 = Warehouse(id=WarehouseType.RAW_MATERIAL, name="Raw", description="raw")
    warehouse2 = Warehouse(id=WarehouseType.PRODUCTION, name="Production", description="production")
    session.add_all([item, warehouse1, warehouse2])
    await session.flush()
    batch = Batch(
        item_id=item.id,
        warehouse_id=warehouse1.id,
        purchase_cost=Decimal("5.00"),
        initial_qty=Decimal("10.00"),
        remaining_qty=Decimal("10.00"),
    )
    session.add(batch)
    await session.flush()
    return item, warehouse1, warehouse2, batch


@pytest.mark.asyncio
async def test_add_stock_and_move(session):
    item, warehouse1, warehouse2, batch = await _setup_items(session)
    new_batch = await add_stock(
        session=session,
        item_id=item.id,
        warehouse_id=warehouse1.id,
        qty=Decimal("5.00"),
        cost=Decimal("5.00"),
        comment="incoming",
    )
    assert new_batch.remaining_qty == Decimal("5.00")

    result = await move_stock(
        session=session,
        item_id=item.id,
        from_warehouse_id=warehouse1.id,
        to_warehouse_id=warehouse2.id,
        qty=Decimal("3.00"),
        comment="move",
    )
    assert result["qty"] == Decimal("3.00")
    assert result["from_warehouse_id"] == warehouse1.id
    assert result["to_warehouse_id"] == warehouse2.id
    await session.refresh(batch)
    assert batch.remaining_qty == Decimal("7.00")


@pytest.mark.asyncio
async def test_adjust_stock_allows_positive_and_negative_delta(session):
    item, warehouse1, warehouse2, _ = await _setup_items(session)

    increase = await adjust_stock(
        session=session,
        item_id=item.id,
        warehouse_id=warehouse1.id,
        delta_qty=Decimal("4.00"),
        comment="adjust-in",
        unit_cost=Decimal("7.00"),
    )
    assert increase["type"] == "increase"
    assert increase["qty"] == Decimal("4.00")

    decrease = await adjust_stock(
        session=session,
        item_id=item.id,
        warehouse_id=warehouse1.id,
        delta_qty=Decimal("-2.00"),
        comment="adjust-out",
    )
    assert decrease["type"] == "decrease"
    assert decrease["qty"] == Decimal("2.00")

    result = await session.execute(
        select(Batch).where(Batch.item_id == item.id, Batch.warehouse_id == warehouse1.id)
    )
    batches = result.scalars().all()
    total_qty = sum((batch.remaining_qty for batch in batches), Decimal("0"))
    assert total_qty == Decimal("12.00")

    txns = await session.execute(
        select(StockTransaction)
        .join(Batch, Batch.id == StockTransaction.batch_id)
        .where(Batch.item_id == item.id, Batch.warehouse_id == warehouse1.id)
    )
    txn_types = {txn.type for txn in txns.scalars().all()}
    assert StockTransactionType.ADJUSTMENT_IN in txn_types
    assert StockTransactionType.ADJUSTMENT_OUT in txn_types


@pytest.mark.asyncio
async def test_move_stock_records_transfer_transactions(session):
    item, warehouse1, warehouse2, _ = await _setup_items(session)

    await move_stock(
        session=session,
        item_id=item.id,
        from_warehouse_id=warehouse1.id,
        to_warehouse_id=warehouse2.id,
        qty=Decimal("2.00"),
        comment="transfer",
    )

    source_batch = await session.scalar(
        select(Batch).where(Batch.item_id == item.id, Batch.warehouse_id == warehouse1.id)
    )
    assert source_batch.remaining_qty == Decimal("8.00")

    destination_batch = await session.scalar(
        select(Batch).where(Batch.item_id == item.id, Batch.warehouse_id == warehouse2.id)
    )
    assert destination_batch.remaining_qty == Decimal("2.00")

    source_txns = await session.execute(
        select(StockTransaction)
        .where(StockTransaction.batch_id == source_batch.id)
    )
    destination_txns = await session.execute(
        select(StockTransaction)
        .where(StockTransaction.batch_id == destination_batch.id)
    )
    assert any(txn.type == StockTransactionType.TRANSFER_OUT for txn in source_txns.scalars().all())
    assert any(txn.type == StockTransactionType.TRANSFER_IN for txn in destination_txns.scalars().all())
