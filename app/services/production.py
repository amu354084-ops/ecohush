from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.schema import (
    BOMHeader,
    BOMItem,
    CashTransaction,
    CashTransactionType,
    OverheadExpense,
    PaymentMethod,
    Sale,
    StockTransactionType,
    WarehouseType,
    ProductionMaterialUsage,
    ProductionOrder,
    ProductionOrderStatus,
)
from app.services.inventory import create_batch, create_stock_transaction, deduct_fifo
from app.services.timezone import get_app_timezone


async def create_production_order(
    session: AsyncSession, batch_number: str, bom_id: int, planned_qty: Decimal
) -> ProductionOrder:
    if not batch_number.strip() or planned_qty <= 0:
        raise ValueError("Batch number and positive planned quantity are required")
    bom = await session.scalar(select(BOMHeader).where(BOMHeader.id == bom_id, BOMHeader.is_active.is_(True)))
    if bom is None:
        raise ValueError("Active BOM not found")
    order = ProductionOrder(
        batch_number=batch_number.strip(), bom_id=bom.id, product_id=bom.product_id,
        planned_qty=planned_qty, status=ProductionOrderStatus.PLANNED,
    )
    session.add(order)
    await session.flush()
    return order


async def complete_production_order(
    session: AsyncSession, order_id: int, actual_qty: Decimal, additional_overheads: Decimal = Decimal(0)
) -> dict[str, Any]:
    if actual_qty <= 0 or additional_overheads < 0:
        raise ValueError("Actual quantity must be positive and overheads non-negative")
    order = await session.scalar(
        select(ProductionOrder).where(ProductionOrder.id == order_id).options(
            selectinload(ProductionOrder.bom).selectinload(BOMHeader.bom_items).selectinload(BOMItem.component)
        )
    )
    if order is None:
        raise ValueError("Production order not found")
    if order.status == ProductionOrderStatus.COMPLETED:
        raise ValueError("Production order is already completed")
    if order.status == ProductionOrderStatus.CANCELLED:
        raise ValueError("Cancelled production order cannot be completed")

    raw_cost_total = Decimal(0)
    usages = []
    for bom_item in order.bom.bom_items:
        required_qty = bom_item.quantity * actual_qty * (Decimal(1) + bom_item.scrap_rate_percent / Decimal(100))
        cost, moves = await deduct_fifo(
            session, bom_item.component_id, required_qty, WarehouseType.RAW_MATERIAL,
            comment=f"Production batch {order.batch_number}",
        )
        raw_cost_total += cost
        session.add(ProductionMaterialUsage(
            production_order_id=order.id, component_id=bom_item.component_id,
            required_qty=required_qty, actual_qty=required_qty, total_cost=cost,
        ))
        usages.append({"component_id": bom_item.component_id, "required_qty": required_qty, "cost": cost, "batch_moves": moves})

    unit_cost = ((raw_cost_total + additional_overheads) / actual_qty).quantize(Decimal("0.0001"))
    finished_batch = await create_batch(session, order.product_id, WarehouseType.FINISHED, unit_cost, actual_qty)
    await create_stock_transaction(session, finished_batch.id, StockTransactionType.PRODUCTION_OUTPUT, actual_qty, f"Production batch {order.batch_number}")
    order.actual_qty = actual_qty
    order.overhead_amount = additional_overheads
    order.status = ProductionOrderStatus.COMPLETED
    order.completed_at = datetime.now(get_app_timezone())
    await session.flush()
    return {"order_id": order.id, "batch_number": order.batch_number, "finished_batch_id": finished_batch.id, "actual_qty": actual_qty, "unit_cost": unit_cost, "usages": usages}


async def execute_production(
    session: AsyncSession,
    bom_id: int,
    output_qty: Decimal,
    additional_overheads: Decimal,
    actual_waste: dict[int, Decimal],
) -> dict[str, Any]:
    if output_qty <= 0:
        raise ValueError("Output quantity must be positive")

    bom = await session.scalar(
        select(BOMHeader)
        .where(BOMHeader.id == bom_id, BOMHeader.is_active.is_(True))
        .options(selectinload(BOMHeader.bom_items).selectinload(BOMItem.component))
    )
    if bom is None:
        raise ValueError("Active BOM not found")

    raw_cost_total = Decimal(0)
    batch_usages: list[dict[str, Any]] = []

    for bom_item in bom.bom_items:
        required_qty = bom_item.quantity * output_qty
        component_item = bom_item.component

        cost, moves = await deduct_fifo(session, component_item.id, required_qty, WarehouseType.RAW_MATERIAL)
        raw_cost_total += cost
        batch_usages.append(
            {
                "component_id": component_item.id,
                "required_qty": required_qty,
                "cost": cost,
                "batch_moves": moves,
            }
        )

    total_production_cost = raw_cost_total + additional_overheads
    unit_cost = (total_production_cost / output_qty).quantize(Decimal("0.0001"))

    finished_batch = await create_batch(
        session=session,
        item_id=bom.product_id,
        warehouse_id=WarehouseType.FINISHED,
        purchase_cost=unit_cost,
        qty=output_qty,
    )

    await create_stock_transaction(
        session=session,
        batch_id=finished_batch.id,
        txn_type=StockTransactionType.PRODUCTION_OUTPUT,
        qty=output_qty,
    )

    scrap_entries: list[dict[str, Any]] = []
    for item_id, waste_qty in actual_waste.items():
        if waste_qty <= 0:
            continue
        waste_batch = await create_batch(
            session=session,
            item_id=item_id,
            warehouse_id=WarehouseType.SCRAP,
            purchase_cost=Decimal(0),
            qty=waste_qty,
        )
        await create_stock_transaction(
            session=session,
            batch_id=waste_batch.id,
            txn_type=StockTransactionType.SCRAP_DISPOSAL,
            qty=waste_qty,
            comment="Production waste"
        )
        scrap_entries.append({"item_id": item_id, "qty": waste_qty})

    overhead_record = OverheadExpense(
        production_run_id=None,
        category="Production overhead",
        amount=additional_overheads,
    )
    session.add(overhead_record)

    await session.flush()

    return {
        "bom_id": bom.id,
        "product_id": bom.product_id,
        "output_qty": output_qty,
        "unit_cost": unit_cost,
        "raw_cost_total": raw_cost_total,
        "additional_overheads": additional_overheads,
        "batch_usages": batch_usages,
        "scrap_entries": scrap_entries,
    }


async def process_return(
    session: AsyncSession,
    sale_id: int,
    defective: bool,
    comment: str,
) -> dict[str, Any]:
    if not comment:
        raise ValueError("Return reason comment is required")

    sale = await session.scalar(
        select(Sale).where(Sale.id == sale_id).options(
            selectinload(Sale.sale_items), selectinload(Sale.counterparty)
        )
    )
    if sale is None:
        raise ValueError("Sale not found")
    if sale.total_amount <= 0:
        raise ValueError("Sale has already been returned")

    original_debt = sale.debt_amount
    refund_amount = sale.total_amount
    cash_refund = min(sale.paid_amount, refund_amount)
    for sale_item in sale.sale_items:
        if defective:
            waste_batch = await create_batch(
                session=session,
                item_id=sale_item.item_id,
                warehouse_id=WarehouseType.SCRAP,
                purchase_cost=Decimal(0),
                qty=sale_item.qty,
            )
            await create_stock_transaction(
                session=session,
                batch_id=waste_batch.id,
                txn_type=StockTransactionType.SCRAP_DISPOSAL,
                qty=sale_item.qty,
                comment=comment,
            )
        else:
            return_batch = await create_batch(
                session=session,
                item_id=sale_item.item_id,
                warehouse_id=WarehouseType.FINISHED,
                purchase_cost=sale_item.cost_price,
                qty=sale_item.qty,
            )
            await create_stock_transaction(
                session=session,
                batch_id=return_batch.id,
                txn_type=StockTransactionType.RETURN,
                qty=sale_item.qty,
                comment=comment,
            )

    sale.total_amount = Decimal(0)
    sale.paid_amount = max(Decimal(0), sale.paid_amount - cash_refund)
    sale.debt_amount = Decimal(0)

    if sale.counterparty_id is not None and original_debt > 0:
        counterparty = sale.counterparty
        counterparty.current_debt = max(Decimal(0), counterparty.current_debt - original_debt)

    if cash_refund > 0:
        session.add(CashTransaction(
            type=CashTransactionType.EXPENSE,
            amount=cash_refund,
            payment_method=PaymentMethod.CASH,
            counterparty_id=sale.counterparty_id,
            description=f"Return processed: {comment}",
        ))
    await session.flush()

    return {
        "sale_id": sale.id,
        "refund_amount": cash_refund,
        "defective": defective,
    }
