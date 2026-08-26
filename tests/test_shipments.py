import pytest
from decimal import Decimal

from app.models.schema import Batch, Item, ItemType, Warehouse, WarehouseType
from app.services.shipments import create_shipment


async def _setup_inventory(session):
    warehouse = Warehouse(id=WarehouseType.FINISHED, name="Finished", description="finished")
    item = Item(code="ITM1", name="Item 1", type=ItemType.FINAL, unit="pcs", min_stock=1)
    session.add_all([warehouse, item])
    await session.flush()
    batch = Batch(
        item_id=item.id,
        warehouse_id=warehouse.id,
        purchase_cost=Decimal("10.00"),
        initial_qty=Decimal("5.00"),
        remaining_qty=Decimal("5.00"),
    )
    session.add(batch)
    await session.flush()
    return warehouse, item, batch


@pytest.mark.asyncio
async def test_create_shipment_reduces_stock(session):
    warehouse, item, batch = await _setup_inventory(session)
    shipment = await create_shipment(
        session=session,
        warehouse_id=warehouse.id,
        recipient_name="Client",
        items=[{"item_id": item.id, "qty": Decimal("2.00"), "unit_price": Decimal("20.00")}],
        note="test",
    )

    assert shipment.id is not None
    assert shipment.total_amount == Decimal("40.00")
    assert shipment.status == "IN_TRANSIT"
    await session.refresh(batch)
    assert batch.remaining_qty == Decimal("3.00")


@pytest.mark.asyncio
async def test_create_shipment_rejects_insufficient_stock(session):
    warehouse, item, _ = await _setup_inventory(session)
    with pytest.raises(ValueError, match="Not enough FIFO stock"):
        await create_shipment(
            session=session,
            warehouse_id=warehouse.id,
            recipient_name="Client",
            items=[{"item_id": item.id, "qty": Decimal("6.00"), "unit_price": Decimal("20.00")}],
            note="test",
        )
