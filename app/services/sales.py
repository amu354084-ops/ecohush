from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import (
    CashTransaction,
    CashTransactionType,
    Counterparty,
    PaymentMethod,
    Sale,
    SaleItem,
    SaleItemBatchAllocation,
    StockTransactionType,
    WarehouseType,
)
from app.services.inventory import deduct_fifo


async def checkout_sale(
    session: AsyncSession,
    counterparty_id: int | None,
    items: list[dict[str, Any]],
    paid_amount: Decimal,
    payment_method: PaymentMethod,
) -> dict[str, Any]:
    if paid_amount < 0:
        raise ValueError("Paid amount must be non-negative")
    if not items:
        raise ValueError("At least one sale item is required")

    total_amount = Decimal(0)
    batch_details: list[dict[str, Any]] = []
    sale_items: list[SaleItem] = []

    for item_data in items:
        item_id = int(item_data["item_id"])
        qty = Decimal(item_data["qty"])
        discount_percent = Decimal(item_data.get("discount_percent", 0))
        if qty <= 0:
            raise ValueError("Item quantity must be positive")
        if discount_percent < 0 or discount_percent > 100:
            raise ValueError("Discount percent must be between 0 and 100")

        cost, moves = await deduct_fifo(
            session=session,
            item_id=item_id,
            required_qty=qty,
            target_warehouse_id=WarehouseType.FINISHED,
            txn_type=StockTransactionType.SALE,
            comment="Sale checkout",
        )
        if any(move["unit_cost"] <= 0 for move in moves):
            raise ValueError("Нельзя оформить продажу: у партии отсутствует себестоимость")
        if any(move["unit_price"] <= 0 for move in moves):
            raise ValueError("Нельзя оформить продажу: у партии отсутствует цена продажи")
        unit_price = sum(
            (move["qty"] * move["unit_price"] for move in moves),
            Decimal(0),
        ) / qty
        discounted_price = unit_price * (Decimal("1") - (discount_percent / Decimal("100")))
        unit_cost = cost / qty if qty != 0 else Decimal(0)

        sale_items.append(
            SaleItem(
                item_id=item_id,
                batch_id=moves[0]["batch_id"] if moves else 0,
                qty=qty,
                unit_price=unit_price,
                cost_price=unit_cost,
                discount_percent=discount_percent,
            )
        )

        item_total = discounted_price * qty
        total_amount += item_total
        batch_details.append(
            {
                "item_id": item_id,
                "qty": qty,
                "unit_price": unit_price,
                "discount_percent": discount_percent,
                "discounted_price": discounted_price,
                "cost": cost,
                "moves": moves,
            }
        )

    if paid_amount > total_amount:
        raise ValueError(f"Paid amount cannot exceed sale total: {total_amount}")
    debt_amount = max(Decimal(0), total_amount - paid_amount)
    sale = Sale(
        counterparty_id=counterparty_id,
        total_amount=total_amount,
        paid_amount=paid_amount,
        debt_amount=debt_amount,
        payment_method=payment_method,
    )
    session.add(sale)
    await session.flush()

    for sale_item, batch_detail in zip(sale_items, batch_details, strict=True):
        sale_item.sale_id = sale.id
        session.add(sale_item)
        for move in batch_detail["moves"]:
            session.add(SaleItemBatchAllocation(
                sale_item=sale_item,
                batch_id=move["batch_id"],
                qty=move["qty"],
                unit_cost=move["unit_cost"],
            ))

    if paid_amount > 0:
        cash_tx = CashTransaction(
            type=CashTransactionType.INCOME,
            amount=paid_amount,
            payment_method=payment_method,
            counterparty_id=counterparty_id,
            description="Sale payment",
        )
        session.add(cash_tx)

    if counterparty_id is not None and debt_amount > 0:
        counterparty = await session.scalar(select(Counterparty).where(Counterparty.id == counterparty_id))
        if counterparty is None:
            raise ValueError("Counterparty not found")
        counterparty.current_debt += debt_amount

    await session.flush()

    return {
        "sale_id": sale.id,
        "total_amount": total_amount,
        "paid_amount": paid_amount,
        "debt_amount": debt_amount,
        "items": [
            {
                "item_id": item.item_id,
                "qty": item.qty,
                "unit_price": item.unit_price,
                "cost_price": item.cost_price,
                "discount_percent": 0,
            }
            for item in sale_items
        ],
        "batch_details": batch_details,
    }


async def repay_client_debt(
    session: AsyncSession,
    client_id: int,
    amount: Decimal,
    payment_method: PaymentMethod,
    description: str = "",
) -> dict[str, Any]:
    if amount <= 0:
        raise ValueError("Сумма погашения должна быть больше нуля")

    counterparty = await session.scalar(select(Counterparty).where(Counterparty.id == client_id))
    if counterparty is None:
        raise ValueError("Клиент не найден")

    sales_result = await session.execute(
        select(Sale)
        .where(Sale.counterparty_id == client_id, Sale.debt_amount > 0)
        .order_by(Sale.created_at, Sale.id)
        .with_for_update()
    )
    debts = list(sales_result.scalars().all())
    outstanding = sum((sale.debt_amount for sale in debts), Decimal(0))
    if amount > outstanding:
        raise ValueError(f"Сумма погашения не может превышать долг: {outstanding}")

    remaining = amount
    allocations: list[dict[str, Any]] = []
    for sale in debts:
        applied = min(remaining, sale.debt_amount)
        sale.debt_amount -= applied
        sale.paid_amount += applied
        remaining -= applied
        allocations.append({"sale_id": sale.id, "amount": applied})
        if remaining <= 0:
            break

    counterparty.current_debt = outstanding - amount
    transaction = CashTransaction(
        type=CashTransactionType.INCOME,
        amount=amount,
        payment_method=payment_method,
        counterparty_id=client_id,
        description=description.strip() or "Погашение долга",
    )
    session.add(transaction)
    await session.flush()
    return {
        "payment_id": transaction.id,
        "client_id": client_id,
        "amount": amount,
        "remaining_debt": counterparty.current_debt,
        "allocations": allocations,
    }
