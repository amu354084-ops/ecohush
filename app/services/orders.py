from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import (
    Counterparty,
    Item,
    Order,
    OrderItem,
    OrderPaymentType,
    OrderStatus,
    User,
)
from app.services.sales import checkout_sale
from app.models.schema import PaymentMethod


async def create_order(
    session: AsyncSession,
    courier_id: int,
    client_id: int,
    items: list[dict[str, Any]],
) -> Order:
    if not items:
        raise ValueError("At least one order item is required")
    courier = await session.get(User, courier_id)
    if courier is None:
        raise ValueError("Courier not found")
    client = await session.get(Counterparty, client_id)
    if client is None:
        raise ValueError("Client not found")

    order = Order(courier_id=courier_id, client_id=client_id, status=OrderStatus.PENDING)
    session.add(order)
    await session.flush()
    for item_data in items:
        quantity = Decimal(item_data["quantity"])
        item = await session.get(Item, int(item_data["item_id"]))
        if item is None:
            raise ValueError("Item not found")
        price = item.price if item_data.get("price") is None else Decimal(item_data["price"])
        discount_percent = item_data.get("discount_percent")
        if discount_percent is not None:
            discount = (
                quantity * price * Decimal(discount_percent) / Decimal("100")
            ).quantize(Decimal("0.01"))
        else:
            discount = Decimal(item_data.get("discount", 0) or 0)
        if quantity <= 0 or price < 0:
            raise ValueError("Order quantity must be positive and price must be non-negative")
        if discount < 0 or discount > quantity * price:
            raise ValueError("Item discount must be between zero and the line subtotal")
        session.add(OrderItem(order_id=order.id, item_id=int(item_data["item_id"]), quantity=quantity, price=price, discount=discount))
    await session.flush()
    await session.refresh(order)
    return order


async def accept_order(session: AsyncSession, order_id: int, discount_amount: Decimal = Decimal(0)) -> Order:
    order = await _get_order(session, order_id)
    if order.status != OrderStatus.PENDING:
        raise ValueError("Only pending orders can be accepted")
    if discount_amount < 0:
        raise ValueError("Discount must be non-negative")
    subtotal = sum((item.quantity * item.price - (item.discount or Decimal(0)) for item in order.items), Decimal(0))
    if discount_amount > subtotal:
        raise ValueError(f"Discount cannot exceed order total: {subtotal}")
    order.discount_amount = discount_amount
    order.status = OrderStatus.ACCEPTED
    order.invoice_number = await _next_invoice_number(session)
    await session.flush()
    return order


async def reject_order(session: AsyncSession, order_id: int, reason: str) -> Order:
    order = await _get_order(session, order_id)
    if order.status != OrderStatus.PENDING:
        raise ValueError("Only pending orders can be rejected")
    if not reason.strip():
        raise ValueError("Rejection reason is required")
    order.status = OrderStatus.REJECTED
    order.rejection_reason = reason.strip()
    await session.flush()
    return order


async def transition_order(
    session: AsyncSession,
    order_id: int,
    status: OrderStatus,
    payment_type: OrderPaymentType | None = None,
    actor: User | None = None,
    paid_amount: Decimal = Decimal(0),
) -> Order:
    order = await _get_order(session, order_id)
    if actor is not None and actor.role == "COURIER" and not actor.can_change_status:
        raise PermissionError("Courier cannot change order status")
    allowed = {
        OrderStatus.ACCEPTED: {OrderStatus.IN_PROGRESS, OrderStatus.IN_TRANSIT},
        OrderStatus.IN_PROGRESS: {OrderStatus.IN_TRANSIT},
        OrderStatus.IN_TRANSIT: {OrderStatus.DELIVERED},
    }
    if status not in allowed.get(order.status, set()):
        raise ValueError(f"Invalid order status transition: {order.status} -> {status}")
    if status == OrderStatus.DELIVERED:
        if payment_type is None:
            raise ValueError("Payment type is required for delivery")
        await _complete_delivery(session, order, payment_type, paid_amount)
    else:
        order.status = status
        await session.flush()
    return order


async def _complete_delivery(
    session: AsyncSession,
    order: Order,
    payment_type: OrderPaymentType,
    paid_amount: Decimal,
) -> None:
    subtotal = sum((item.quantity * item.price for item in order.items), Decimal(0))
    item_discounts = sum((item.discount or Decimal(0) for item in order.items), Decimal(0))
    total = max(Decimal(0), subtotal - item_discounts - (order.discount_amount or Decimal(0)))
    if paid_amount > total:
        raise ValueError(f"Оплата не может быть больше суммы заказа: {total}")
    if payment_type == OrderPaymentType.DEBT and paid_amount != 0:
        raise ValueError("Для оплаты в долг сумма оплаты должна быть равна нулю")
    sale_items = [
        {
            "item_id": item.item_id,
            "qty": item.quantity,
            "unit_price": item.price,
            "discount_percent": (
                ((item.discount or Decimal(0)) / (item.quantity * item.price) * Decimal(100))
                if item.quantity * item.price else Decimal(0)
            ),
        }
        for item in order.items
    ]
    await checkout_sale(
        session=session,
        counterparty_id=order.client_id,
        items=sale_items,
        paid_amount=paid_amount,
        payment_method=PaymentMethod.BANK if payment_type == OrderPaymentType.BANK else PaymentMethod.CASH,
    )
    order.status = OrderStatus.DELIVERED
    order.payment_type = payment_type
    order.delivered_at = datetime.now(timezone.utc)
    await session.flush()


async def _get_order(session: AsyncSession, order_id: int) -> Order:
    order = await session.get(Order, order_id)
    if order is None:
        raise ValueError("Order not found")
    await session.refresh(order, attribute_names=["items"])
    return order


async def _next_invoice_number(session: AsyncSession) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    numbers = (await session.scalars(select(Order.invoice_number))).all()
    suffixes = [
        int(match.group(1))
        for number in numbers
        if number and (match := re.fullmatch(r"\d{8}-(\d+)", number))
    ]
    return f"{day}-{max(suffixes, default=0) + 1:04d}"


async def renumber_invoice_numbers(session: AsyncSession) -> None:
    orders = (await session.execute(
        select(Order)
        .where(Order.invoice_number.is_not(None))
        .order_by(Order.created_at, Order.id)
    )).scalars().all()
    invoice_days = {
        order.id: (
            match.group(1)
            if (match := re.match(r"^(\d{8})-\d+$", order.invoice_number or ""))
            else order.created_at.strftime("%Y%m%d")
        )
        for order in orders
    }

    for order in orders:
        order.invoice_number = f"__renumbering__{order.id}"
    await session.flush()

    for index, order in enumerate(orders, 1):
        order.invoice_number = f"{invoice_days[order.id]}-{index:04d}"
    await session.flush()
