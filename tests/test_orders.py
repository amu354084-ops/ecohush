from decimal import Decimal
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.schema import (
    Base,
    Counterparty,
    Item,
    ItemType,
    Order,
    OrderPaymentType,
    OrderStatus,
    User,
    Warehouse,
    WarehouseType,
)
from app.services.inventory import create_batch
from app.services.orders import accept_order, create_order, delete_order, renumber_invoice_numbers, reverse_delivered_order, transition_order, update_order
from app.services.invoice import invoice_html


@pytest.mark.asyncio
async def test_order_delivers_and_posts_fifo_debt_only_at_delivery():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        courier = User(username="courier", password_hash="test", role="COURIER", can_change_status=True)
        client = Counterparty(name="Client", phone="79000000000")
        item = Item(code="ORDER-1", name="Product", type=ItemType.FINAL, unit="pcs", min_stock=0, price=Decimal("99"))
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="Finished", description="test")
        session.add_all([courier, client, item, warehouse])
        await session.flush()
        batch = await create_batch(
            session, item.id, warehouse.id, Decimal("2"), Decimal("3"), Decimal("10")
        )

        order = await create_order(
            session,
            courier.id,
            client.id,
            [{"item_id": item.id, "quantity": Decimal("2"), "price": Decimal("10")}],
        )
        await session.refresh(batch)
        assert order.status == OrderStatus.PENDING
        assert order.invoice_number is None
        await session.refresh(order, attribute_names=["items"])
        assert order.items[0].price == Decimal("10.0000")
        assert batch.remaining_qty == Decimal("3.0000")

        await accept_order(session, order.id)
        assert order.status == OrderStatus.ACCEPTED
        assert order.invoice_number.endswith("-0001")
        await transition_order(session, order.id, OrderStatus.IN_TRANSIT, actor=courier)
        await transition_order(
            session, order.id, OrderStatus.DELIVERED,
            payment_type=OrderPaymentType.DEBT, actor=courier,
        )
        await session.refresh(batch)
        await session.refresh(client)
        assert order.status == OrderStatus.DELIVERED
        assert batch.remaining_qty == Decimal("1.0000")
        assert client.current_debt == Decimal("20.00")

    await engine.dispose()


@pytest.mark.asyncio
async def test_order_item_discount_percent_is_converted_to_amount():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        courier = User(username="percent-courier", password_hash="test", role="COURIER")
        client = Counterparty(name="Percent Client")
        item = Item(code="PERCENT-1", name="Percent Product", type=ItemType.FINAL, unit="pcs", min_stock=0, price=Decimal("100"))
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="Finished", description="test")
        session.add_all([courier, client, item, warehouse])
        await session.flush()
        await create_batch(session, item.id, warehouse.id, Decimal("2"), Decimal("2"), Decimal("100"))

        order = await create_order(
            session, courier.id, client.id,
            [{"item_id": item.id, "quantity": 2, "price": 100, "discount_percent": 3}],
        )
        await session.refresh(order, attribute_names=["items"])
        assert order.items[0].discount == Decimal("6.00")

    await engine.dispose()


@pytest.mark.asyncio
async def test_order_accept_rejects_discount_above_total():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        courier = User(username="discount-limit-courier", password_hash="test", role="COURIER")
        client = Counterparty(name="Discount Limit Client")
        item = Item(code="DISCOUNT-LIMIT", name="Discount Limit Product", type=ItemType.FINAL, unit="pcs", min_stock=0, price=Decimal("10"))
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="Finished", description="test")
        session.add_all([courier, client, item, warehouse])
        await session.flush()
        await create_batch(session, item.id, warehouse.id, Decimal("2"), Decimal("2"), Decimal("10"))
        order = await create_order(session, courier.id, client.id, [{"item_id": item.id, "quantity": 2, "price": 10}])
        with pytest.raises(ValueError, match="cannot exceed order total"):
            await accept_order(session, order.id, Decimal("21"))

    await engine.dispose()


@pytest.mark.asyncio
async def test_existing_invoice_numbers_are_renumbered_globally():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        first = Order(invoice_number="20260825-0007", created_at=datetime(2026, 8, 25, 9, 0))
        second = Order(invoice_number="20260826-0001", created_at=datetime(2026, 8, 26, 10, 0))
        session.add_all([first, second])
        await session.flush()

        await renumber_invoice_numbers(session)

        assert first.invoice_number == "20260825-0001"
        assert second.invoice_number == "20260826-0002"

    await engine.dispose()


@pytest.mark.asyncio
async def test_order_can_be_updated_before_acceptance_and_deleted_only_before_acceptance():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        courier = User(username="edit-courier", password_hash="test", role="COURIER")
        first_client = Counterparty(name="First Client")
        second_client = Counterparty(name="Second Client")
        item = Item(code="EDIT-1", name="Editable Product", type=ItemType.FINAL, unit="pcs", min_stock=0)
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="Finished", description="test")
        session.add_all([courier, first_client, second_client, item, warehouse])
        await session.flush()
        await create_batch(session, item.id, warehouse.id, Decimal("2"), Decimal("2"), Decimal("10"))
        order = await create_order(session, courier.id, first_client.id, [{"item_id": item.id, "quantity": 2, "discount_percent": 0}], "Первый источник")
        await update_order(session, order.id, second_client.id, [{"item_id": item.id, "quantity": 1, "discount_percent": 10}], "Чалбкунанnda")
        await session.refresh(order, attribute_names=["items"])
        assert order.client_id == second_client.id
        assert order.referred_by == "Чалбкунанnda"
        assert order.items[0].quantity == Decimal("1.0000")
        assert order.items[0].discount == Decimal("1.00")
        await delete_order(session, order.id)
        assert await session.get(Order, order.id) is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_accepted_order_cannot_be_deleted():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        courier = User(username="delete-courier", password_hash="test", role="COURIER")
        client = Counterparty(name="Delete Client")
        item = Item(code="DELETE-1", name="Delete Product", type=ItemType.FINAL, unit="pcs", min_stock=0)
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="Finished", description="test")
        session.add_all([courier, client, item, warehouse])
        await session.flush()
        await create_batch(session, item.id, warehouse.id, Decimal("2"), Decimal("2"), Decimal("10"))
        order = await create_order(session, courier.id, client.id, [{"item_id": item.id, "quantity": 1}])
        await accept_order(session, order.id)
        with pytest.raises(ValueError, match="Удалять можно только"):
            await delete_order(session, order.id)
    await engine.dispose()


@pytest.mark.asyncio
async def test_delivered_order_can_be_reversed_with_stock_and_debt_returned():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        courier = User(username="reverse-courier", password_hash="test", role="COURIER", can_change_status=True)
        client = Counterparty(name="Reverse Client")
        item = Item(code="REVERSE-1", name="Reverse Product", type=ItemType.FINAL, unit="pcs", min_stock=0)
        warehouse = Warehouse(id=WarehouseType.FINISHED, name="Finished", description="test")
        session.add_all([courier, client, item, warehouse])
        await session.flush()
        batch = await create_batch(session, item.id, warehouse.id, Decimal("2"), Decimal("2"), Decimal("10"))
        order = await create_order(session, courier.id, client.id, [{"item_id": item.id, "quantity": 1}])
        await accept_order(session, order.id)
        await transition_order(session, order.id, OrderStatus.IN_TRANSIT, actor=courier)
        await transition_order(session, order.id, OrderStatus.DELIVERED, OrderPaymentType.DEBT, courier)
        await session.refresh(order)
        assert order.sale_id is not None
        assert client.current_debt == Decimal("10.00")
        await reverse_delivered_order(session, order)
        await session.refresh(batch)
        await session.refresh(client)
        assert order.status == OrderStatus.PENDING
        assert order.sale_id is None
        assert batch.remaining_qty == Decimal("1.0000")
        assert client.current_debt == Decimal("0.00")
    await engine.dispose()


def test_order_invoice_subtracts_item_and_order_discounts_from_total():
    item = SimpleNamespace(name="Product", unit="pcs")
    order = SimpleNamespace(
        invoice_number="20260906-0001",
        id=1,
        created_at=datetime(2026, 9, 6, 12, 0),
        status=OrderStatus.DELIVERED,
        client=SimpleNamespace(name="Client"),
        courier=SimpleNamespace(full_name="Courier", username="courier"),
        discount_amount=Decimal("10.00"),
        items=[SimpleNamespace(item=item, quantity=Decimal("2"), price=Decimal("100"), discount=Decimal("5"))],
    )
    html = invoice_html(order)
    assert "<th>200.00</th><th>15.00</th><th>185.00</th>" in html
    assert "на сумму 185.00 сомони" in html
