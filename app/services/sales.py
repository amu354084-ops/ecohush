from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import (
    AuditEvent,
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
from app.services.timezone import to_db_datetime

PAYMENT_AUDIT_ENTITY = "payment"
SALE_PAYMENT_DESCRIPTION = "Sale payment"
DUPLICATE_PAYMENT_WINDOW = timedelta(seconds=60)


def _payment_snapshot(transaction: CashTransaction, allocations: list[dict[str, Any]]) -> str:
    method = transaction.payment_method
    return json.dumps({
        "payment_id": transaction.id,
        "amount": str(transaction.amount),
        "payment_method": getattr(method, "value", str(method)),
        "description": transaction.description or "",
        "created_at": transaction.created_at.isoformat() if transaction.created_at else None,
        "allocations": [{"sale_id": item["sale_id"], "amount": str(item["amount"])} for item in allocations],
    }, ensure_ascii=False)


def payment_can_be_cancelled(transaction: CashTransaction) -> bool:
    """Debt repayments can be cancelled; cash taken at checkout belongs to the sale itself."""
    return (
        transaction.type == CashTransactionType.INCOME
        and transaction.counterparty_id is not None
        and (transaction.description or "") != SALE_PAYMENT_DESCRIPTION
    )


async def checkout_sale(
    session: AsyncSession,
    counterparty_id: int | None,
    items: list[dict[str, Any]],
    paid_amount: Decimal,
    payment_method: PaymentMethod,
    use_item_prices: bool = False,
    total_discount: Decimal = Decimal(0),
) -> dict[str, Any]:
    """Create a sale.

    ``use_item_prices`` is used for orders: the price the client agreed to (and saw on the
    invoice) is taken from ``item["unit_price"]`` instead of the current FIFO batch prices.
    """
    if paid_amount < 0:
        raise ValueError("Paid amount must be non-negative")
    if not items:
        raise ValueError("At least one sale item is required")
    counterparty: Counterparty | None = None
    if counterparty_id is not None:
        counterparty = await session.get(Counterparty, counterparty_id)
        if counterparty is None:
            raise ValueError("Counterparty not found")

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
        agreed_price = item_data.get("unit_price") if use_item_prices else None
        if agreed_price is not None:
            unit_price = Decimal(agreed_price)
            if unit_price <= 0:
                raise ValueError("Нельзя оформить продажу: в заявке отсутствует цена")
        else:
            if any(move["unit_price"] <= 0 for move in moves):
                raise ValueError("Нельзя оформить продажу: у партии отсутствует цена продажи")
            unit_price = sum(
                (move["qty"] * move["unit_price"] for move in moves),
                Decimal(0),
            ) / qty
        line_discount = item_data.get("discount_amount") if use_item_prices else None
        if line_discount is not None:
            # Order lines store the discount in money; use it as is.  Converting it to a
            # percent and back produced totals like 350.1399999... and the payment of
            # 350.14 was then rejected as "bigger than the sale total".
            line_discount = Decimal(line_discount)
            if line_discount < 0 or line_discount > unit_price * qty:
                raise ValueError("Скидка по строке должна быть от нуля до суммы строки")
            item_total = (unit_price * qty - line_discount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            discounted_price = item_total / qty
        else:
            discounted_price = unit_price * (Decimal("1") - (discount_percent / Decimal("100")))
            item_total = (discounted_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
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

    if total_discount < 0:
        raise ValueError("Discount must be non-negative")
    # Whole-order discount (set when an order is accepted) reduces the amount the client owes.
    total_amount = max(Decimal(0), total_amount - total_discount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if paid_amount > total_amount:
        raise ValueError(f"Оплата не может быть больше суммы продажи: {total_amount}")
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
                unit_price=move["unit_price"],
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

    if counterparty is not None and debt_amount > 0:
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
                "discount_percent": item.discount_percent,
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
    actor_id: int | None = None,
) -> dict[str, Any]:
    if amount <= 0:
        raise ValueError("Сумма погашения должна быть больше нуля")

    counterparty = await session.scalar(select(Counterparty).where(Counterparty.id == client_id))
    if counterparty is None:
        raise ValueError("Клиент не найден")

    # Protection against a double click on "Принять оплату": the same amount for the
    # same client within a minute is almost always an accidental duplicate.
    recent_since = to_db_datetime(datetime.now(timezone.utc) - DUPLICATE_PAYMENT_WINDOW)
    duplicate_id = await session.scalar(
        select(CashTransaction.id).where(
            CashTransaction.counterparty_id == client_id,
            CashTransaction.type == CashTransactionType.INCOME,
            CashTransaction.amount == amount,
            CashTransaction.created_at >= recent_since,
        ).limit(1)
    )
    if duplicate_id is not None:
        raise ValueError(
            f"Такая же оплата ({amount}) от этого клиента уже принята меньше минуты назад (платёж №{duplicate_id}). "
            "Если это действительно второй платёж, повторите через минуту"
        )

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

    counterparty.current_debt = max(Decimal(0), (counterparty.current_debt or Decimal(0)) - amount)
    transaction = CashTransaction(
        type=CashTransactionType.INCOME,
        amount=amount,
        payment_method=payment_method,
        counterparty_id=client_id,
        description=description.strip() or "Погашение долга",
    )
    session.add(transaction)
    await session.flush()
    # Remember how the payment was spread over sales so it can be cancelled exactly.
    session.add(AuditEvent(
        entity_type=PAYMENT_AUDIT_ENTITY, entity_id=transaction.id, counterparty_id=client_id,
        actor_id=actor_id, action="CREATED", reason=transaction.description or "",
        after_data=_payment_snapshot(transaction, allocations),
    ))
    await session.flush()
    return {
        "payment_id": transaction.id,
        "client_id": client_id,
        "amount": amount,
        "remaining_debt": counterparty.current_debt,
        "allocations": allocations,
    }


async def cancel_client_payment(
    session: AsyncSession,
    payment_id: int,
    reason: str,
    actor_id: int | None = None,
) -> dict[str, Any]:
    """Cancel a mistaken debt repayment.

    The debt returns to the sales the payment had paid off and the cash income is
    removed.  A full snapshot of the payment is kept in the audit log.
    """
    reason = reason.strip()
    if not reason:
        raise ValueError("Укажите причину отмены платежа")
    transaction = await session.get(CashTransaction, payment_id)
    if transaction is None:
        raise ValueError("Платёж не найден")
    if not payment_can_be_cancelled(transaction):
        raise ValueError("Отменить можно только погашение долга клиента")
    counterparty = await session.get(Counterparty, transaction.counterparty_id)
    if counterparty is None:
        raise ValueError("Клиент не найден")

    amount = Decimal(transaction.amount)
    created_event = await session.scalar(
        select(AuditEvent).where(
            AuditEvent.entity_type == PAYMENT_AUDIT_ENTITY,
            AuditEvent.entity_id == transaction.id,
            AuditEvent.action == "CREATED",
        ).order_by(AuditEvent.id.desc()).limit(1)
    )
    reversals: list[tuple[Sale, Decimal]] = []
    recorded = json.loads(created_event.after_data or "{}").get("allocations") if created_event else None
    if recorded:
        # Exact reversal: the payment remembered which sales it paid.
        for item in recorded:
            sale = await session.get(Sale, int(item["sale_id"]), with_for_update=True)
            share = Decimal(item["amount"])
            if sale is None or sale.paid_amount < share:
                raise ValueError(f"Продажа №{item['sale_id']} изменилась, отменить платёж автоматически нельзя")
            reversals.append((sale, share))
    else:
        # Older payments did not store their allocation.  Repayments are applied to the
        # oldest sale first, so the amount is taken back from the newest sales that
        # existed at the time of the payment.
        candidates = (await session.execute(
            select(Sale)
            .where(
                Sale.counterparty_id == counterparty.id,
                Sale.total_amount > 0,
                Sale.paid_amount > 0,
                Sale.created_at <= transaction.created_at,
            )
            .order_by(Sale.created_at.desc(), Sale.id.desc())
            .with_for_update()
        )).scalars().all()
        remaining = amount
        for sale in candidates:
            if remaining <= 0:
                break
            share = min(remaining, Decimal(sale.paid_amount))
            reversals.append((sale, share))
            remaining -= share
        if remaining > 0:
            raise ValueError("Не удалось найти продажи, на которые был распределён этот платёж")

    before_data = _payment_snapshot(
        transaction, [{"sale_id": sale.id, "amount": share} for sale, share in reversals]
    )
    for sale, share in reversals:
        sale.paid_amount -= share
        sale.debt_amount += share
    counterparty.current_debt = (counterparty.current_debt or Decimal(0)) + amount
    session.add(AuditEvent(
        entity_type=PAYMENT_AUDIT_ENTITY, entity_id=transaction.id, counterparty_id=counterparty.id,
        actor_id=actor_id, action="CANCELLED", reason=reason, before_data=before_data,
    ))
    await session.delete(transaction)
    await session.flush()
    debt_total = await session.scalar(
        select(func.coalesce(func.sum(Sale.debt_amount), 0)).where(Sale.counterparty_id == counterparty.id)
    )
    return {
        "payment_id": payment_id,
        "client_id": counterparty.id,
        "amount": amount,
        "sales_debt": Decimal(debt_total or 0),
        "returned_to_sales": [{"sale_id": sale.id, "amount": share} for sale, share in reversals],
    }
