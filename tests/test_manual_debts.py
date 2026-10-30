from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.clients_api import (
    ArchiveClientRequest,
    ManualDebtCreateRequest,
    ManualDebtDeleteRequest,
    ManualDebtRequest,
    SaleDebtWriteOffRequest,
    create_manual_debt,
    archive_client,
    delete_manual_debt,
    list_clients,
    list_manual_debts,
    update_manual_debt,
    write_off_sale_debt,
)
from app.models.schema import AuditEvent, Base, CashTransaction, Counterparty, Sale, User


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

        await delete_manual_debt(entry.id, ManualDebtDeleteRequest(reason="Duplicate entry"), admin, session)
        clients = await list_clients(None, 100, 0, None, admin, session)
        assert Decimal(clients[0].current_debt) == Decimal("75.00")
        assert await session.scalar(select(func.count()).select_from(CashTransaction)) == 0
        await session.refresh(sale)
        assert sale.debt_amount == Decimal("75.00")
        audit = (await session.execute(select(AuditEvent).order_by(AuditEvent.id))).scalars().all()
        assert [event.action for event in audit] == ["CREATED", "UPDATED", "DELETED"]
        assert audit[-1].reason == "Duplicate entry"

    await engine.dispose()


@pytest.mark.asyncio
async def test_archiving_debtor_hides_client_but_preserves_financial_history():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        admin = User(username="archive-admin", password_hash="test", role="ADMIN")
        client = Counterparty(name="Archived debtor")
        session.add_all([admin, client])
        await session.flush()
        sale = Sale(counterparty_id=client.id, total_amount=Decimal("75"), paid_amount=Decimal("0"), debt_amount=Decimal("75"))
        session.add(sale)
        await session.commit()

        result = await archive_client(client.id, ArchiveClientRequest(reason="Клиент больше не работает"), admin, session)
        visible_clients = await list_clients(None, 100, 0, None, admin, session)
        assert result["archived"] is True
        assert visible_clients == []
        assert await session.get(Counterparty, client.id) is not None
        assert await session.get(Sale, sale.id) is not None
        audit = await session.scalar(select(AuditEvent).where(AuditEvent.counterparty_id == client.id))
        assert audit.action == "ARCHIVED"
        assert audit.reason == "Клиент больше не работает"
    await engine.dispose()


@pytest.mark.asyncio
async def test_sale_debt_can_be_written_off_with_reason_without_deleting_sale():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        admin = User(username="writeoff-admin", password_hash="test", role="ADMIN")
        client = Counterparty(name="Write-off client", current_debt=Decimal("75.00"))
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

        result = await write_off_sale_debt(
            sale.id,
            SaleDebtWriteOffRequest(reason="Клиентский долг списан по согласованию"),
            admin,
            session,
        )

        await session.refresh(client)
        assert result == {"sale_id": sale.id, "written_off": True, "amount": "75.00"}
        assert sale.total_amount == Decimal("100.00")
        assert sale.debt_amount == Decimal("0.00")
        assert client.current_debt == Decimal("0.00")
        assert await session.get(Sale, sale.id) is not None
        event = await session.scalar(select(AuditEvent).where(AuditEvent.entity_type == "sale_debt"))
        assert event.action == "WRITTEN_OFF"
        assert event.reason == "Клиентский долг списан по согласованию"

    await engine.dispose()
