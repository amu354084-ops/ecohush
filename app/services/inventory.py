from __future__ import annotations

from decimal import Decimal
from datetime import datetime
from io import BytesIO
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import (
    Batch,
    Item,
    StockTransaction,
    StockTransactionType,
    Warehouse,
)
from app.services.localization import display_label


async def deduct_fifo(
    session: AsyncSession,
    item_id: int,
    required_qty: Decimal,
    target_warehouse_id: int,
    txn_type: StockTransactionType = StockTransactionType.PRODUCTION_INPUT,
    comment: str | None = None,
) -> tuple[Decimal, list[dict[str, Any]]]:
    """Deduct quantity using FIFO batches and return total cost and batch details."""
    if required_qty <= 0:
        raise ValueError("Required quantity must be positive")

    query = (
        select(Batch).options(selectinload(Batch.item))
        .where(
            Batch.item_id == item_id,
            Batch.warehouse_id == target_warehouse_id,
            Batch.remaining_qty > 0,
        )
        .order_by(Batch.created_at.asc())
        .with_for_update()
    )

    result = await session.execute(query)
    batches = result.scalars().all()

    remaining_required = required_qty
    total_cost = Decimal(0)
    batch_moves: list[dict[str, Any]] = []

    for batch in batches:
        if remaining_required <= 0:
            break

        deduct_qty = min(batch.remaining_qty, remaining_required)
        batch.remaining_qty -= deduct_qty
        line_cost = deduct_qty * batch.purchase_cost
        total_cost += line_cost
        remaining_required -= deduct_qty

        batch_moves.append(
            {
                "batch_id": batch.id,
                "qty": deduct_qty,
                "unit_cost": batch.purchase_cost,
                "unit_price": batch.sale_price,
                "line_cost": line_cost,
            }
        )

        # create a stock transaction for this deducted qty
        await create_stock_transaction(
            session=session,
            batch_id=batch.id,
            txn_type=txn_type,
            qty=-deduct_qty,
            comment=comment,
        )

    if remaining_required > 0:
        raise ValueError(
            f"Not enough FIFO stock: недостаточно остатка товара (ID {item_id}) на складе готовой продукции. "
            "Проверьте остатки или уменьшите количество в заказе."
        )

    await session.flush()
    return total_cost, batch_moves


async def create_batch(
    session: AsyncSession,
    item_id: int,
    warehouse_id: int,
    purchase_cost: Decimal,
    qty: Decimal,
    sale_price: Decimal | None = None,
) -> Batch:
    if purchase_cost < 0:
        raise ValueError("Purchase cost must be non-negative")
    if qty <= 0:
        raise ValueError("Batch quantity must be positive")
    if sale_price is not None and sale_price < 0:
        raise ValueError("Sale price must be non-negative")

    item = await session.get(Item, item_id)
    if item is None:
        raise ValueError("Item not found")

    batch = Batch(
        item_id=item_id,
        warehouse_id=warehouse_id,
        purchase_cost=purchase_cost,
        sale_price=sale_price if sale_price is not None else item.price,
        initial_qty=qty,
        remaining_qty=qty,
    )
    session.add(batch)
    await session.flush()
    await session.refresh(batch)
    return batch


async def adjust_stock(
    session: AsyncSession,
    item_id: int,
    warehouse_id: int,
    delta_qty: Decimal,
    comment: str | None = None,
    unit_cost: Decimal | None = None,
) -> dict[str, Any]:
    if delta_qty == 0:
        raise ValueError("Adjustment quantity must not be zero")

    if delta_qty > 0:
        cost = unit_cost if unit_cost is not None else Decimal("0")
        batch = await create_batch(
            session=session,
            item_id=item_id,
            warehouse_id=warehouse_id,
            purchase_cost=cost,
            qty=delta_qty,
        )
        await create_stock_transaction(
            session=session,
            batch_id=batch.id,
            txn_type=StockTransactionType.ADJUSTMENT_IN,
            qty=delta_qty,
            comment=comment or "Inventory adjustment",
        )
        return {"type": "increase", "batch_id": batch.id, "qty": delta_qty}

    required_qty = abs(delta_qty)
    total_cost, moves = await deduct_fifo(
        session=session,
        item_id=item_id,
        required_qty=required_qty,
        target_warehouse_id=warehouse_id,
        txn_type=StockTransactionType.ADJUSTMENT_OUT,
        comment=comment or "Inventory adjustment",
    )
    return {"type": "decrease", "qty": required_qty, "total_cost": total_cost, "moves": moves}


async def create_stock_transaction(
    session: AsyncSession,
    batch_id: int,
    txn_type: StockTransactionType,
    qty: Decimal,
    comment: str | None = None,
) -> StockTransaction:
    txn = StockTransaction(
        batch_id=batch_id,
        type=txn_type,
        qty=qty,
        comment=comment,
    )
    session.add(txn)
    await session.flush()
    return txn


async def get_stock_summary(
    session: AsyncSession,
    warehouse_id: int | None = None,
) -> list[dict[str, str | int]]:
    from sqlalchemy import func, select

    stmt = (
        select(
            Batch.warehouse_id,
            Warehouse.name.label("warehouse_name"),
            Batch.item_id,
            Item.code.label("item_code"),
            Item.name.label("item_name"),
            Item.unit,
            func.sum(Batch.remaining_qty).label("remaining_qty"),
        )
        .join(Warehouse, Warehouse.id == Batch.warehouse_id)
        .join(Item, Item.id == Batch.item_id)
        .group_by(Batch.warehouse_id, Warehouse.name, Batch.item_id, Item.code, Item.name, Item.unit)
    )
    if warehouse_id is not None:
        stmt = stmt.where(Batch.warehouse_id == warehouse_id)

    result = await session.execute(stmt)
    rows = [
        {
            "warehouse_id": row.warehouse_id,
            "warehouse_name": row.warehouse_name,
            "item_id": row.item_id,
            "item_code": row.item_code,
            "item_name": row.item_name,
            "unit": row.unit,
            "remaining_qty": str(row.remaining_qty or 0),
        }
        for row in result
    ]
    return sorted(
        rows,
        key=lambda row: (
            str(row["warehouse_name"]).casefold(),
            str(row["item_code"]).casefold(),
            str(row["item_name"]).casefold(),
        ),
    )


async def get_stock_history(
    session: AsyncSession,
    warehouse_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int | None = 500,
    offset: int = 0,
) -> list[dict[str, str | int]]:
    from sqlalchemy.orm import selectinload

    stmt = (
        select(StockTransaction)
        .join(StockTransaction.batch)
        .options(
            selectinload(StockTransaction.batch).selectinload(Batch.item),
            selectinload(StockTransaction.batch).selectinload(Batch.warehouse),
        )
        .order_by(StockTransaction.timestamp.desc(), StockTransaction.id.desc())
    )
    if warehouse_id is not None:
        stmt = stmt.where(Batch.warehouse_id == warehouse_id)
    if date_from is not None:
        stmt = stmt.where(StockTransaction.timestamp >= date_from)
    if date_to is not None:
        stmt = stmt.where(StockTransaction.timestamp <= date_to)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)

    result = await session.execute(stmt)
    rows: list[dict[str, str | int]] = []
    for transaction in result.scalars().all():
        batch = transaction.batch
        if batch.item is None or batch.warehouse is None:
            continue
        rows.append({
            "id": transaction.id,
            "timestamp": transaction.timestamp.isoformat(),
            "warehouse_name": batch.warehouse.name,
            "item_code": batch.item.code,
            "item_name": batch.item.name,
            "unit": batch.item.unit,
            "operation": display_label(transaction.type.value),
            "qty": str(transaction.qty),
            "comment": transaction.comment or "",
        })
    return rows


async def export_stock_history_excel(
    session: AsyncSession,
    warehouse_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[bytes, str, str]:
    import csv
    import io

    history_rows = await get_stock_history(session, warehouse_id, date_from, date_to)
    header_map = {
        "timestamp": "Дата",
        "warehouse_name": "Склад",
        "item_code": "Код",
        "item_name": "Наименование",
        "unit": "Ед.",
        "operation": "Операция",
        "qty": "Количество",
        "comment": "Комментарий",
    }
    rows = [{key: row[key] for key in header_map} for row in history_rows]
    suffix = warehouse_id if warehouse_id is not None else "all"
    filename = f"stock_history_{suffix}.xlsx"
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    try:
        import pandas as pd

        buf = BytesIO()
        df = pd.DataFrame(rows).rename(columns=header_map).fillna("")
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="История")
        return buf.getvalue(), filename, media_type
    except Exception:
        fieldnames = list(header_map.values())
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({header_map[key]: row[key] or "" for key in header_map})
        return output.getvalue().encode("utf-8-sig"), f"stock_history_{suffix}.csv", "text/csv"


async def export_stock_summary_excel(
    session: AsyncSession,
    warehouse_id: int | None = None,
) -> tuple[bytes, str, str]:
    stock_rows = await get_stock_summary(session=session, warehouse_id=warehouse_id)
    filename = f"stock_warehouse_{warehouse_id if warehouse_id is not None else 'all'}.xlsx"
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    # Use Russian headers for export
    header_map = {
        "item_code": "Код",
        "item_name": "Наименование",
        "unit": "Ед.",
        "warehouse_name": "Склад",
        "remaining_qty": "Остаток",
    }

    rows = [
        {
            "item_code": row["item_code"],
            "item_name": row["item_name"],
            "unit": row["unit"],
            "warehouse_name": row["warehouse_name"],
            "remaining_qty": row["remaining_qty"],
        }
        for row in stock_rows
    ]

    try:
        import pandas as pd

        df = pd.DataFrame(rows)
        df = df.rename(columns=header_map).fillna("")
        buf = BytesIO()
        writer = pd.ExcelWriter(buf, engine="openpyxl")
        df.to_excel(writer, index=False, sheet_name="Остатки")
        writer.close()
        return buf.getvalue(), filename, media_type
    except Exception:
        import csv
        import io

        if rows:
            fieldnames = [header_map[k] for k in rows[0].keys()]
        else:
            fieldnames = list(header_map.values())

        s = io.StringIO()
        writer = csv.DictWriter(s, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            mapped = {header_map[k]: ("" if v is None else v) for k, v in r.items()}
            writer.writerow(mapped)
        data = s.getvalue().encode("utf-8-sig")
        filename = f"stock_warehouse_{warehouse_id if warehouse_id is not None else 'all'}.csv"
        return data, filename, "text/csv"
