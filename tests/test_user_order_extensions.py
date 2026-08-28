from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.schema import Base, CashTransaction, Counterparty, Item, ItemType, OrderPaymentType, OrderStatus, Sale, User, Warehouse, WarehouseType
from app.services.auth import create_token, hash_password
from app.services.inventory import create_batch
from app.services.orders import accept_order, create_order, transition_order


@pytest.mark.asyncio
async def test_order_item_discount_is_used_at_delivery():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        courier = User(username="discount-courier", password_hash=hash_password("x"), role="COURIER", can_change_status=True)
        client = Counterparty(name="Discount Client", current_debt=Decimal(0))
        item = Item(code="DISC-1", name="Discount Product", type=ItemType.FINAL, unit="pcs", min_stock=0, price=Decimal("10"))
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="Finished", description="test")
        session.add_all([courier, client, item, warehouse])
        await session.flush()
        batch = await create_batch(session, item.id, warehouse.id, Decimal("2"), Decimal("2"))
        order = await create_order(session, courier.id, client.id, [{"item_id": item.id, "quantity": 2, "price": 10, "discount": 3}])
        await accept_order(session, order.id)
        await transition_order(session, order.id, OrderStatus.IN_TRANSIT, actor=courier)
        await transition_order(session, order.id, OrderStatus.DELIVERED, OrderPaymentType.CASH, courier, paid_amount=5)
        await session.refresh(client)
        await session.refresh(batch)
        sale = await session.scalar(select(Sale).where(Sale.counterparty_id == client.id))
        cash = await session.scalar(select(CashTransaction).where(CashTransaction.counterparty_id == client.id))
        assert sale.paid_amount == Decimal("5.00")
        assert sale.debt_amount == Decimal("12.00")
        assert cash.amount == Decimal("5.00")
        assert client.current_debt == Decimal("12.00")
        assert batch.remaining_qty == Decimal("0.0000")
    await engine.dispose()


def test_token_creation_is_available_for_active_user():
    user = User(id=4, username="active", password_hash="test", role="ADMIN", is_active=True)
    assert create_token(user)
