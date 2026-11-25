from decimal import Decimal

import pytest

from app.models.schema import (
    Counterparty,
    Item,
    ItemType,
    OrderPaymentType,
    OrderStatus,
    Sale,
    User,
    Warehouse,
    WarehouseType,
)
from app.services.orders import accept_order, create_order, transition_order
from app.services.warehouse_ops import add_stock


async def _deliver(session, price, qty, item_percent, general_discount, paid, payment=OrderPaymentType.CASH):
    session.add(Warehouse(id=WarehouseType.FINISHED, name="Готовая продукция"))
    item = Item(code="P1", name="Товар", type=ItemType.FINAL, unit="шт")
    seller = User(username="seller", password_hash="x", role="ADMIN")
    client = Counterparty(name="Магазин", current_debt=Decimal(0))
    session.add_all([item, seller, client])
    await session.flush()
    await add_stock(session, item.id, WarehouseType.FINISHED, Decimal(100), Decimal(1), sale_price=Decimal(price))
    order = await create_order(session, seller.id, client.id, [
        {"item_id": item.id, "quantity": Decimal(qty), "discount_percent": Decimal(item_percent)},
    ])
    await accept_order(session, order.id, Decimal(general_discount))
    await transition_order(session, order.id, OrderStatus.IN_TRANSIT)
    order = await transition_order(session, order.id, OrderStatus.DELIVERED, payment, paid_amount=Decimal(paid))
    return await session.get(Sale, order.sale_id)


@pytest.mark.asyncio
async def test_full_payment_with_line_and_general_discount_is_accepted(session):
    # 125.50 x 3 = 376.50, 7% line discount = 26.36, general discount 5 -> 345.14.
    # This used to fail with "Paid amount cannot exceed sale total: 345.1399999...".
    sale = await _deliver(session, "125.5", "3", "7", "5", "345.14")
    assert sale.total_amount == Decimal("345.14")
    assert sale.paid_amount == Decimal("345.14")
    assert sale.debt_amount == Decimal("0")


@pytest.mark.asyncio
async def test_general_discount_reduces_debt(session):
    sale = await _deliver(session, "125.5", "7", "7", "13.37", "0", payment=OrderPaymentType.DEBT)
    # 878.50 - 61.50 (7%) - 13.37 = 803.63
    assert sale.total_amount == Decimal("803.63")
    assert sale.debt_amount == Decimal("803.63")


@pytest.mark.asyncio
async def test_general_discount_above_order_total_has_clear_message(session):
    with pytest.raises(ValueError, match="Общая скидка"):
        await _deliver(session, "10", "1", "0", "13.37", "0")
