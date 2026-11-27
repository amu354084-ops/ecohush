from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from app.models.schema import (
    Counterparty,
    Item,
    ItemType,
    ManualDebt,
    OrderPaymentType,
    OrderStatus,
    User,
    Warehouse,
    WarehouseType,
)
from app.services.debtors import build_debtors_workbook
from app.services.invoice import invoice_html
from app.services.orders import accept_order, create_order, transition_order
from app.services.production import process_return
from app.services.sale_lines import distribute
from app.services.warehouse_ops import add_stock


def test_general_discount_is_split_exactly_over_products():
    parts = distribute(
        [("a", Decimal("100"), Decimal("0")), ("b", Decimal("200"), Decimal("0")), ("c", Decimal("33.33"), Decimal("0"))],
        final_total=Decimal("323.33"),
    )
    assert sum((part.general_discount for part in parts), Decimal(0)) == Decimal("10.00")
    assert sum((part.net for part in parts), Decimal(0)) == Decimal("323.33")
    # Proportional: the 200 line gets about twice the share of the 100 line.
    assert parts[1].general_discount == Decimal("6.00")
    assert parts[0].general_discount == Decimal("3.00")


async def _setup(session):
    session.add(Warehouse(id=WarehouseType.FINISHED, name="Готовая продукция"))
    gel = Item(code="GEL", name="Гель", type=ItemType.FINAL, unit="шт")
    powder = Item(code="PWD", name="Порошок", type=ItemType.FINAL, unit="кг")
    seller = User(username="seller", password_hash="x", role="ADMIN")
    client = Counterparty(name="Магазин", phone="900", current_debt=Decimal(0))
    session.add_all([gel, powder, seller, client])
    await session.flush()
    await add_stock(session, gel.id, WarehouseType.FINISHED, Decimal(100), Decimal(5), sale_price=Decimal("30"))
    await add_stock(session, powder.id, WarehouseType.FINISHED, Decimal(100), Decimal(5), sale_price=Decimal("70"))
    return gel, powder, seller, client


async def _delivered_order(session, gel, powder, seller, client, paid, general="20"):
    order = await create_order(session, seller.id, client.id, [
        {"item_id": gel.id, "quantity": Decimal(10), "discount_percent": Decimal(10)},  # 300 - 30
        {"item_id": powder.id, "quantity": Decimal(3)},  # 210
    ])
    await accept_order(session, order.id, Decimal(general))
    await transition_order(session, order.id, OrderStatus.IN_TRANSIT)
    return await transition_order(session, order.id, OrderStatus.DELIVERED, OrderPaymentType.CASH,
                                  paid_amount=Decimal(paid))


@pytest.mark.asyncio
async def test_order_invoice_shows_general_discount_split_over_products(session):
    gel, powder, seller, client = await _setup(session)
    order = await _delivered_order(session, gel, powder, seller, client, paid="0")
    await session.refresh(order, attribute_names=["items", "client", "courier"])
    for line in order.items:
        await session.refresh(line, attribute_names=["item"])
    html = invoice_html(SimpleNamespace(**{
        "created_at": order.created_at, "items": order.items, "discount_amount": order.discount_amount,
        "invoice_number": order.invoice_number, "id": order.id, "client": order.client,
        "courier": order.courier, "status": order.status,
    }))
    # 270 + 210 = 480, minus general 20 = 460
    assert "460.00" in html
    assert "общая скидка на заказ: 20.00" in html


@pytest.mark.asyncio
async def test_debtors_export_matches_debts_and_splits_general_discount(session):
    gel, powder, seller, client = await _setup(session)
    await _delivered_order(session, gel, powder, seller, client, paid="160")  # total 460 -> debt 300
    session.add(ManualDebt(counterparty_id=client.id, amount=Decimal("50"), description="старый долг"))
    await session.flush()

    data, filename = await build_debtors_workbook(session)
    workbook = load_workbook(BytesIO(data))
    assert filename.endswith(".xlsx")

    summary = list(workbook["Должники"].iter_rows(min_row=2, values_only=True))
    assert summary[0][:5] == ("Магазин", "900", 300.0, 50.0, 350.0)

    sales = list(workbook["Неоплаченные продажи"].iter_rows(min_row=2, values_only=True))
    # gross 510, line discount 30, general 20, total 460, paid 160, debt 300
    assert sales[0][5:11] == (510.0, 30.0, 20.0, 460.0, 160.0, 300.0)

    lines = [row for row in workbook["Товары в долг"].iter_rows(min_row=2, values_only=True) if row[0] != "ИТОГО"]
    assert sum(row[9] for row in lines) == pytest.approx(20.0)  # general discount split over products
    assert sum(row[10] for row in lines) == pytest.approx(460.0)
    assert sum(row[11] for row in lines) == pytest.approx(300.0)  # unpaid parts add up to the sale debt


@pytest.mark.asyncio
async def test_returned_order_leaves_no_debt_in_export(session):
    gel, powder, seller, client = await _setup(session)
    order = await _delivered_order(session, gel, powder, seller, client, paid="0")
    await process_return(session, order.sale_id, defective=False, comment="возврат")

    data, _ = await build_debtors_workbook(session)
    workbook = load_workbook(BytesIO(data))
    assert list(workbook["Должники"].iter_rows(min_row=2, values_only=True)) == []
    assert list(workbook["Неоплаченные продажи"].iter_rows(min_row=2, values_only=True)) == []
