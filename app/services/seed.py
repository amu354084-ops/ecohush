from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import (
    Batch,
    BOMHeader,
    BOMItem,
    Counterparty,
    Item,
    ItemType,
    Sale,
    SaleItem,
    Warehouse,
    WarehouseType,
    User,
)
from app.services.auth import hash_password


def initial_admin_password() -> str | None:
    value = os.getenv("ERP_INITIAL_ADMIN_PASSWORD")
    if value:
        return value
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, separator, candidate = line.partition("=")
            if separator and key.strip() == "ERP_INITIAL_ADMIN_PASSWORD":
                return candidate.strip().strip('"').strip("'") or None
    return None


async def get_one(session: AsyncSession, model: type, *filters):
    return await session.scalar(select(model).where(*filters))


async def ensure_warehouse(session: AsyncSession, id: int, name: str, description: str) -> Warehouse:
    warehouse = await get_one(session, Warehouse, Warehouse.id == id)
    if warehouse is None:
        warehouse = Warehouse(id=id, name=name, description=description)
        session.add(warehouse)
        await session.flush()
    return warehouse


async def ensure_item(session: AsyncSession, code: str, name: str, type: ItemType, unit: str, min_stock: int) -> Item:
    item = await get_one(session, Item, Item.code == code)
    if item is None:
        item = Item(code=code, name=name, type=type, unit=unit, min_stock=min_stock)
        session.add(item)
        await session.flush()
    return item


async def ensure_bom(
    session: AsyncSession,
    product: Item,
    name: str,
    components: Iterable[tuple[Item, Decimal, Decimal]],
) -> BOMHeader:
    bom = await get_one(session, BOMHeader, BOMHeader.product_id == product.id)
    if bom is None:
        bom = BOMHeader(product_id=product.id, name=name, is_active=True)
        session.add(bom)
        await session.flush()
        for component, quantity, scrap_rate_percent in components:
            bom_item = BOMItem(
                bom_id=bom.id,
                component_id=component.id,
                quantity=quantity,
                scrap_rate_percent=scrap_rate_percent,
            )
            session.add(bom_item)
        await session.flush()
    return bom


async def ensure_batch(
    session: AsyncSession,
    item: Item,
    warehouse_id: int,
    purchase_cost: Decimal,
    qty: Decimal,
) -> Batch:
    batch = await session.scalar(
        select(Batch).where(
            Batch.item_id == item.id,
            Batch.warehouse_id == warehouse_id,
            Batch.remaining_qty > 0,
        )
    )
    if batch is None:
        batch = Batch(
            item_id=item.id,
            warehouse_id=warehouse_id,
            purchase_cost=purchase_cost,
            initial_qty=qty,
            remaining_qty=qty,
        )
        session.add(batch)
        await session.flush()
    return batch


async def ensure_counterparty(session: AsyncSession, name: str, phone: str | None = None) -> Counterparty:
    counterparty = await get_one(session, Counterparty, Counterparty.name == name)
    if counterparty is None:
        counterparty = Counterparty(name=name, phone=phone, current_debt=Decimal(0))
        session.add(counterparty)
        await session.flush()
    return counterparty


async def ensure_sale_sample(
    session: AsyncSession,
    product: Item,
    batch: Batch,
    counterparty: Counterparty,
) -> Sale:
    sale = await get_one(session, Sale, Sale.id == 1)
    if sale is None:
        sale = Sale(
            id=1,
            counterparty_id=counterparty.id,
            total_amount=Decimal("55.00"),
            paid_amount=Decimal("55.00"),
            debt_amount=Decimal("0.00"),
        )
        session.add(sale)
        await session.flush()
        sale_item = SaleItem(
            sale_id=sale.id,
            item_id=product.id,
            batch_id=batch.id,
            qty=Decimal("1.00"),
            unit_price=Decimal("55.00"),
            cost_price=Decimal("50.00"),
        )
        session.add(sale_item)
        await session.flush()
    return sale


async def seed_initial_data(session: AsyncSession) -> None:
    admin = await get_one(session, User, User.username == "admin")
    if admin is None:
        initial_password = initial_admin_password()
        if not initial_password:
            raise RuntimeError("ERP_INITIAL_ADMIN_PASSWORD must be set before creating the initial admin")
        admin = User(
            username="admin",
            password_hash=hash_password(initial_password),
            full_name="Администратор",
            role="ADMIN",
            can_change_status=True,
            must_change_password=os.getenv("ERP_DISABLE_INITIAL_PASSWORD_CHANGE") != "1",
        )
        session.add(admin)
        await session.flush()

    await ensure_warehouse(session, WarehouseType.RAW_MATERIAL, "Склад сырья", "Склад сырья и комплектующих")
    await ensure_warehouse(session, WarehouseType.PRODUCTION, "Цех", "Производственный участок")
    await ensure_warehouse(session, WarehouseType.FINISHED, "Готовая продукция", "Склад готовой продукции")
    await ensure_warehouse(session, WarehouseType.SCRAP, "Брак и отходы", "Зона брака и отходов")

    if os.getenv("ERP_SEED_DEMO_DATA") != "1":
        return

    chem1 = await ensure_item(session, "CHEM1", "Химический компонент 1", ItemType.RAW, "л", 10)
    chem2 = await ensure_item(session, "CHEM2", "Химический компонент 2", ItemType.RAW, "л", 8)
    pack = await ensure_item(session, "PKG1", "Упаковка", ItemType.RAW, "шт", 5)
    product = await ensure_item(session, "PRD1", "Финишный продукт", ItemType.FINAL, "шт", 2)

    await ensure_bom(
        session,
        product=product,
        name="Продукт A",
        components=[
            (chem1, Decimal("2.00"), Decimal("0.00")),
            (chem2, Decimal("1.50"), Decimal("0.00")),
            (pack, Decimal("1.00"), Decimal("0.00")),
        ],
    )

    raw_warehouse = await ensure_warehouse(
        session,
        WarehouseType.RAW_MATERIAL,
        "Склад сырья",
        "Склад сырья и комплектующих",
    )
    finished_warehouse = await ensure_warehouse(
        session,
        WarehouseType.FINISHED,
        "Готовая продукция",
        "Склад готовой продукции",
    )

    await ensure_batch(session, chem1, raw_warehouse.id, Decimal("10.00"), Decimal("50.00"))
    await ensure_batch(session, chem2, raw_warehouse.id, Decimal("18.00"), Decimal("30.00"))
    await ensure_batch(session, pack, raw_warehouse.id, Decimal("5.00"), Decimal("40.00"))

    finished_batch = await ensure_batch(session, product, finished_warehouse.id, Decimal("50.00"), Decimal("10.00"))
    counterpart = await ensure_counterparty(session, "Магазин №1", "+7 900 000-00-01")
    await ensure_sale_sample(session, product, finished_batch, counterpart)
