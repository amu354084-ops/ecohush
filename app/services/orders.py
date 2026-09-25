from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import (
    Batch,
    Counterparty,
    Item,
    Order,
    OrderItem,
    OrderPaymentType,
    OrderStatus,
    User,
    WarehouseType,
)
from app.services.sales import checkout_sale
from app.services.production import process_return
from app.models.schema import PaymentMethod
from app.services.timezone import get_app_timezone


async def create_order(
    session: AsyncSession,
    courier_id: int,
    client_id: int,
    items: list[dict[str, Any]],
    referred_by: str | None = None,
) -> Order:
    if not items:
        raise ValueError("At least one order item is required")
    courier = await session.get(User, courier_id)
    if courier is None:
        raise ValueError("Courier not found")
    client = await session.get(Counterparty, client_id)
    if client is None:
        raise ValueError("Client not found")

    order = Order(
        courier_id=courier_id,
        client_id=client_id,
        referred_by=(referred_by or "").strip() or None,
        status=OrderStatus.PENDING,
    )
    session.add(order)
    await session.flush()
    for item_data in items:
        quantity = Decimal(item_data["quantity"])
        item = await session.get(Item, int(item_data["item_id"]))
        if item is None:
            raise ValueError("Item not found")
        batch_price = await session.scalar(
            select(Batch.sale_price)
            .where(
                Batch.item_id == item.id,
                Batch.warehouse_id == WarehouseType.FINISHED,
                Batch.remaining_qty > 0,
                Batch.sale_price > 0,
            )
            .order_by(Batch.created_at.asc(), Batch.id.asc())
        )
        if batch_price is None:
            raise ValueError("Для товара нет активной партии с ценой продажи")
        price = batch_price
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


async def update_order(
    session: AsyncSession,
    order_id: int,
    client_id: int,
    items: list[dict[str, Any]],
    referred_by: str | None = None,
) -> Order:
    order = await _get_order(session, order_id)
    if order.status not in {OrderStatus.PENDING, OrderStatus.ACCEPTED, OrderStatus.REJECTED}:
        raise ValueError("Заявку можно изменять только до передачи в путь")
    client = await session.get(Counterparty, client_id)
    if client is None:
        raise ValueError("Client not found")
    if not items:
        raise ValueError("At least one order item is required")
    order.client_id = client_id
    order.referred_by = (referred_by or "").strip() or None
    order.rejection_reason = None
    await session.execute(delete(OrderItem).where(OrderItem.order_id == order.id))
    for item_data in items:
        item = await session.get(Item, int(item_data["item_id"]))
        if item is None:
            raise ValueError("Item not found")
        quantity = Decimal(item_data["quantity"])
        price = await session.scalar(
            select(Batch.sale_price).where(
                Batch.item_id == item.id,
                Batch.warehouse_id == WarehouseType.FINISHED,
                Batch.remaining_qty > 0,
                Batch.sale_price > 0,
            ).order_by(Batch.created_at.asc(), Batch.id.asc())
        )
        if price is None:
            raise ValueError("Для товара нет активной партии с ценой продажи")
        discount_percent = item_data.get("discount_percent")
        if discount_percent is not None:
            discount = (quantity * price * Decimal(discount_percent) / Decimal("100")).quantize(Decimal("0.01"))
        else:
            discount = Decimal(item_data.get("discount", 0) or 0)
        if quantity <= 0 or discount < 0 or discount > quantity * price:
            raise ValueError("Некорректное количество или скидка")
        session.add(OrderItem(order_id=order.id, item_id=item.id, quantity=quantity, price=price, discount=discount))
    if order.status == OrderStatus.REJECTED:
        order.status = OrderStatus.PENDING
    await session.flush()
    return order


async def delete_order(session: AsyncSession, order_id: int) -> None:
    order = await _get_order(session, order_id)
    if order.status not in {OrderStatus.PENDING, OrderStatus.REJECTED}:
        raise ValueError("Удалять можно только заявку до одобрения")
    await session.delete(order)
    await session.flush()


async def reverse_delivered_order(session: AsyncSession, order: Order) -> None:
    if order.status != OrderStatus.DELIVERED:
        return
    if order.sale_id is None:
        raise ValueError("Для этой доставленной заявки не найдена связанная продажа")
    await process_return(
        session=session,
        sale_id=order.sale_id,
        defective=False,
        comment=f"Сторнирование заявки №{order.id}",
    )
    order.status = OrderStatus.PENDING
    order.invoice_number = None
    order.payment_type = None
    order.sale_id = None
    order.delivered_at = None
    order.discount_amount = Decimal(0)
    await session.flush()


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
    sale = await checkout_sale(
        session=session,
        counterparty_id=order.client_id,
        items=sale_items,
        paid_amount=paid_amount,
        payment_method=PaymentMethod.BANK if payment_type == OrderPaymentType.BANK else PaymentMethod.CASH,
    )
    order.status = OrderStatus.DELIVERED
    order.payment_type = payment_type
    order.sale_id = sale["sale_id"]
    order.delivered_at = datetime.now(get_app_timezone())
    await session.flush()


async def _get_order(session: AsyncSession, order_id: int) -> Order:
    order = await session.get(Order, order_id)
    if order is None:
        raise ValueError("Order not found")
    await session.refresh(order, attribute_names=["items"])
    return order


async def _next_invoice_number(session: AsyncSession) -> str:
    day = datetime.now(get_app_timezone()).strftime("%Y%m%d")
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
