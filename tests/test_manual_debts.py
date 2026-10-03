from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.clients_api import (
    ManualDebtCreateRequest,
    ManualDebtRequest,
    create_manual_debt,
    delete_manual_debt,
    list_clients,
    list_manual_debts,
    update_manual_debt,
)
from app.models.schema import Base, CashTransaction, Counterparty, Sale, User


@pytest.mark.asyncio
async def test_manual_debt_can_be_added_edited_and_deleted_without_payment():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        admin = User(username="debt-admin", password_hash="test", role="ADMIN")
        client = Counterparty(name="Manual Debt Client")
        session.add_all([admin, client])
        await session.flush()
        sale = Sale(
            counterparty_id=client.id,
            total_amount=Decimal("100.00"),
            paid_amount=Decimal("25.00"),
            debt_amount=Decimal("75.00"),
        )
        session.add(sale)
        await session.commit()

        entry = await create_manual_debt(
            ManualDebtCreateRequest(client_id=client.id, amount=Decimal("20.00"), description="Opening balance"),
            admin,
            session,
        )
        debts = await list_manual_debts(client.id, admin, session)
        clients = await list_clients(None, 100, 0, None, admin, session)
        assert debts[0].id == entry.id
        assert Decimal(clients[0].current_debt) == Decimal("95.00")

        await update_manual_debt(
            entry.id,
            ManualDebtRequest(amount=Decimal("35.00"), description="Corrected balance"),
            admin,
            session,
        )
        clients = await list_clients(None, 100, 0, None, admin, session)
        assert Decimal(clients[0].current_debt) == Decimal("110.00")

        await delete_manual_debt(entry.id, admin, session)
        clients = await list_clients(None, 100, 0, None, admin, session)
        assert Decimal(clients[0].current_debt) == Decimal("75.00")
        assert await session.scalar(select(func.count()).select_from(CashTransaction)) == 0
        await session.refresh(sale)
        assert sale.debt_amount == Decimal("75.00")

    await engine.dispose()
