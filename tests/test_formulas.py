import pytest
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.schema import Base, Item, ItemType
from app.services.formulas import create_formula


async def _setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, AsyncSessionLocal


@pytest.mark.asyncio
async def test_create_formula_creates_bom_and_components():
    engine, AsyncSessionLocal = await _setup_db()
    async with AsyncSessionLocal() as session:
        product = Item(code="P1", name="Shampoo", type=ItemType.FINAL, unit="pcs", min_stock=5)
        component = Item(code="R1", name="Water", type=ItemType.RAW, unit="l", min_stock=2)
        session.add_all([product, component])
        await session.flush()

        formula = await create_formula(
            session=session,
            product_id=product.id,
            name="Shampoo recipe",
            components=[{"component_id": component.id, "quantity": Decimal("2.5"), "scrap_rate_percent": Decimal("0")}],
        )

        assert formula.name == "Shampoo recipe"
        assert len(formula.bom_items) == 1
        assert formula.bom_items[0].quantity == Decimal("2.5")

    await engine.dispose()
