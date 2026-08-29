from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import Batch, Item, StockTransactionType
from app.services.inventory import create_stock_transaction


async def add_stock(
    session: AsyncSession,
    item_id: int,
    warehouse_id: int,
    qty: Decimal,
    cost: Decimal,
    comment: str | None = None,
    txn_type: StockTransactionType = StockTransactionType.INBOUND,
    sale_price: Decimal | None = None,
) -> Batch:
    if qty <= 0:
        raise ValueError("Quantity must be positive")
    if cost < 0:
        raise ValueError("Cost must be non-negative")

    item = await session.get(Item, item_id)
    if item is None:
        raise ValueError("Item not found")
    if sale_price is not None and sale_price < 0:
        raise ValueError("Sale price must be non-negative")
    item.price = sale_price if sale_price is not None else cost

    batch = Batch(
        item_id=item_id,
        warehouse_id=warehouse_id,
        purchase_cost=cost,
        sale_price=sale_price if sale_price is not None else item.price,
        initial_qty=qty,
        remaining_qty=qty,
    )
    session.add(batch)
    await session.flush()
    await session.refresh(batch)
    await create_stock_transaction(session, batch.id, txn_type, qty, comment or "Inbound")
    return batch


async def move_stock(
    session: AsyncSession,
    item_id: int,
    from_warehouse_id: int,
    to_warehouse_id: int,
    qty: Decimal,
    comment: str | None = None,
    cost: Decimal | None = None,
) -> dict[str, Any]:
    if qty <= 0:
        raise ValueError("Quantity must be positive")
    if from_warehouse_id == to_warehouse_id:
        raise ValueError("Source and destination warehouses must differ")

    source_batches = await session.execute(
        select(Batch)
        .where(Batch.item_id == item_id, Batch.warehouse_id == from_warehouse_id, Batch.remaining_qty > 0)
        .order_by(Batch.created_at.asc())
    )
    batches = source_batches.scalars().all()
    remaining = qty
    moved = []
    for batch in batches:
        if remaining <= 0:
            break
        deduct_qty = min(batch.remaining_qty, remaining)
        batch.remaining_qty -= deduct_qty
        remaining -= deduct_qty
        moved.append({
            "batch_id": batch.id,
            "qty": deduct_qty,
            "purchase_cost": batch.purchase_cost,
            "sale_price": batch.sale_price,
        })
        await create_stock_transaction(
            session,
            batch.id,
            StockTransactionType.TRANSFER_OUT,
            -deduct_qty,
            comment or "Move out",
        )

    if remaining > 0:
        raise ValueError("Not enough stock to move")

    destination_batches = []
    for moved_batch in moved:
        destination_batches.append(
            await add_stock(
                session,
                item_id,
                to_warehouse_id,
                moved_batch["qty"],
                cost if cost is not None else moved_batch["purchase_cost"],
                comment or "Move in",
                StockTransactionType.TRANSFER_IN,
                moved_batch["sale_price"],
            )
        )
    return {
        "item_id": item_id,
        "qty": qty,
        "from_warehouse_id": from_warehouse_id,
        "to_warehouse_id": to_warehouse_id,
        "destination_batch_id": destination_batches[0].id,
    }
