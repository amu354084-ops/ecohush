from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.orders_api import remove as remove_order
from app.models.schema import (
    Base,
    Batch,
    CashTransaction,
    CashTransactionType,
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
from app.services.inventory import create_batch
from app.services.orders import accept_order, create_order, transition_order


@pytest.mark.asyncio
async def test_deleting_delivered_order_returns_stock_and_refunds_cash():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        admin = User(username="return-admin", password_hash="test", role="ADMIN")
        courier = User(username="return-courier", password_hash="test", role="COURIER", can_change_status=True)
        client = Counterparty(name="Return Client")
        item = Item(code="RETURN-DELETE", name="Return Product", type=ItemType.FINAL, unit="pcs", min_stock=0)
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="Finished", description="test")
        session.add_all([admin, courier, client, item, warehouse])
        await session.flush()
        await create_batch(session, item.id, warehouse.id, Decimal("2"), Decimal("2"), Decimal("10"))
        order = await create_order(session, courier.id, client.id, [{"item_id": item.id, "quantity": 1}])
        await accept_order(session, order.id)
        await transition_order(session, order.id, OrderStatus.IN_TRANSIT, actor=courier)
        await transition_order(
            session,
            order.id,
            OrderStatus.DELIVERED,
            OrderPaymentType.CASH,
            actor=courier,
            paid_amount=Decimal("5.00"),
        )
        await session.refresh(order)
        sale_id = order.sale_id
        order.sale_id = None
        await session.flush()

        await remove_order(order.id, admin, session)

        assert await session.get(type(order), order.id) is None
        sale = await session.get(Sale, sale_id)
        assert sale is not None
        assert sale.total_amount == Decimal("0.00")
        assert sale.debt_amount == Decimal("0.00")
        await session.refresh(client)
        assert client.current_debt == Decimal("0.00")
        returned_stock = await session.scalar(
            select(func.sum(Batch.remaining_qty)).where(
                Batch.item_id == item.id,
                Batch.warehouse_id == WarehouseType.FINISHED,
            )
        )
        assert returned_stock == Decimal("2.0000")
        refund = await session.scalar(
            select(func.sum(CashTransaction.amount)).where(CashTransaction.type == CashTransactionType.EXPENSE)
        )
        assert refund == Decimal("5.00")

    await engine.dispose()
