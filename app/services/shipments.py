from __future__ import annotations

from io import BytesIO
from typing import Any

from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.schema import (
    Shipment,
    ShipmentItem,
    StockTransactionType,
)
from app.services.inventory import deduct_fifo


async def create_shipment(
    session: AsyncSession,
    warehouse_id: int,
    recipient_name: str,
    items: list[dict[str, Any]],
    note: str | None = None,
) -> Shipment:
    shipment = Shipment(warehouse_id=warehouse_id, recipient_name=recipient_name, note=note)
    session.add(shipment)
    await session.flush()

    total_amount = Decimal(0)

    for it in items:
        item_id = int(it["item_id"])
        qty: Decimal = Decimal(it["qty"])

        discount_percent = Decimal(it.get("discount_percent", 0) or 0)
        if discount_percent < 0 or discount_percent > 100:
            raise ValueError("Discount percent must be between 0 and 100")
        discount_multiplier = (Decimal(100) - discount_percent) / Decimal(100)

        # Deduct from FIFO batches and create ShipmentItem rows for each batch portion
        _, batch_moves = await deduct_fifo(
            session=session,
            item_id=item_id,
            required_qty=qty,
            target_warehouse_id=warehouse_id,
            txn_type=StockTransactionType.SALE,
            comment=f"Shipment to {recipient_name}",
        )
        if any(move["unit_cost"] <= 0 for move in batch_moves):
            raise ValueError("Нельзя оформить отгрузку: у партии отсутствует себестоимость")
        if any(move["unit_price"] <= 0 for move in batch_moves):
            raise ValueError("Нельзя оформить отгрузку: у партии отсутствует цена продажи")

        for mv in batch_moves:
            effective_price = mv["unit_price"]
            si = ShipmentItem(
                shipment_id=shipment.id,
                item_id=item_id,
                batch_id=mv["batch_id"],
                qty=mv["qty"],
                unit_price=effective_price,
                discount_percent=discount_percent,
                cost_price=mv["unit_cost"],
            )
            session.add(si)
            total_amount += effective_price * mv["qty"] * discount_multiplier

    shipment.total_amount = total_amount
    shipment.status = "IN_TRANSIT"
    await session.flush()
    await session.refresh(shipment)
    return shipment


async def get_shipments(session: AsyncSession) -> list[Shipment]:
    result = await session.execute(select(Shipment).order_by(Shipment.created_at.desc()))
    # lightweight: use ORM query in callers if more detail is needed
    return result.fetchall()


async def export_shipment_excel(session: AsyncSession, shipment_id: int) -> tuple[bytes, str]:
    # Build a simple Excel invoice for the shipment. Use pandas if available.
    from sqlalchemy import select

    from app.models.schema import Shipment, ShipmentItem, Item

    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise NotFoundError("Shipment not found")

    stmt = select(ShipmentItem).where(ShipmentItem.shipment_id == shipment_id)
    res = await session.execute(stmt)
    items = res.scalars().all()

    rows = []
    for it in items:
        item = await session.get(Item, it.item_id)
        rows.append(
            {
                "ItemCode": item.code if item else "",
                "ItemName": item.name if item else "",
                "Qty": float(it.qty),
                "UnitPrice": float(it.unit_price) if it.unit_price is not None else "",
                "DiscountPercent": float(it.discount_percent) if it.discount_percent is not None else 0.0,
                "CostPrice": float(it.cost_price) if it.cost_price is not None else "",
            }
        )
    total_amount = sum(
        Decimal(row["Qty"]) * Decimal(str(row["UnitPrice"] or 0)) *
        (Decimal(100) - Decimal(str(row["DiscountPercent"] or 0))) / Decimal(100)
        for row in rows
    )
    rows.append({
        "ItemCode": "",
        "ItemName": "ИТОГО К ОПЛАТЕ",
        "Qty": "",
        "UnitPrice": float(total_amount.quantize(Decimal("0.01"))),
        "DiscountPercent": "",
        "CostPrice": "",
    })

    # Map English keys to Russian headers for Excel/CSV exports
    header_map = {
        "ItemCode": "Код",
        "ItemName": "Наименование",
        "Qty": "Кол-во",
        "UnitPrice": "Цена",
        "DiscountPercent": "Скидка %",
        "CostPrice": "Себестоимость",
    }

    try:
        import pandas as pd

        df = pd.DataFrame(rows)
        # Rename columns to Russian headers and replace NaN/None/'None' with empty strings
        df = df.rename(columns=header_map).fillna("")
        df = df.replace([None, "None"], "")
        buf = BytesIO()
        writer = pd.ExcelWriter(buf, engine="openpyxl")
        df.to_excel(writer, index=False, sheet_name="Invoice")
        writer.close()
        data = buf.getvalue()
        filename = f"invoice_shipment_{shipment_id}.xlsx"
        return data, filename, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    except Exception:
        import csv
        import io

        if rows:
            # Use Russian fieldnames for CSV as well
            fieldnames = [header_map.get(k, k) for k in list(rows[0].keys())]
        else:
            fieldnames = [
                header_map["ItemCode"],
                header_map["ItemName"],
                header_map["Qty"],
                header_map["UnitPrice"],
                header_map["DiscountPercent"],
                header_map["CostPrice"],
            ]

        s = io.StringIO()
        writer = csv.DictWriter(s, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            # Map each row's keys to Russian headers and sanitize None
            mapped = {header_map.get(k, k): ("" if v is None else v) for k, v in r.items()}
            writer.writerow(mapped)
        # Use utf-8-sig so Excel on Windows recognizes Cyrillic correctly
        data = s.getvalue().encode("utf-8-sig")
        filename = f"invoice_shipment_{shipment_id}.csv"
        return data, filename, "text/csv"
