from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.schema import BOMHeader, BOMItem


async def create_formula(
    session: AsyncSession,
    product_id: int,
    name: str,
    components: list[dict[str, Any]],
) -> BOMHeader:
    bom = BOMHeader(product_id=product_id, name=name, is_active=True)
    session.add(bom)
    await session.flush()

    for component in components:
        bom_item = BOMItem(
            bom_id=bom.id,
            component_id=int(component["component_id"]),
            quantity=Decimal(str(component["quantity"])),
            scrap_rate_percent=Decimal(str(component.get("scrap_rate_percent", 0))),
        )
        session.add(bom_item)

    await session.flush()
    result = await session.execute(
        select(BOMHeader).options(selectinload(BOMHeader.bom_items)).where(BOMHeader.id == bom.id)
    )
    return result.scalar_one()


async def update_formula(
    session: AsyncSession,
    bom_id: int,
    product_id: int,
    name: str,
    components: list[dict[str, Any]],
) -> BOMHeader:
    bom = await session.get(BOMHeader, bom_id)
    if bom is None:
        raise ValueError("Формула не найдена")
    bom.product_id = product_id
    bom.name = name
    await session.flush()

    await session.execute(delete(BOMItem).where(BOMItem.bom_id == bom_id))
    for component in components:
        bom_item = BOMItem(
            bom_id=bom.id,
            component_id=int(component["component_id"]),
            quantity=Decimal(str(component["quantity"])),
            scrap_rate_percent=Decimal(str(component.get("scrap_rate_percent", 0))),
        )
        session.add(bom_item)

    await session.flush()
    result = await session.execute(
        select(BOMHeader).options(selectinload(BOMHeader.bom_items)).where(BOMHeader.id == bom.id)
    )
    return result.scalar_one()
<<<<<<< HEAD


async def delete_formula(session: AsyncSession, bom_id: int) -> None:
    bom = await session.get(BOMHeader, bom_id)
    if bom is None:
        raise ValueError("Формула не найдена")
    await session.execute(delete(BOMItem).where(BOMItem.bom_id == bom_id))
    await session.delete(bom)
    await session.flush()
=======
>>>>>>> 79337643694e5ea8d1ab2f5dd562210de6645ad0
