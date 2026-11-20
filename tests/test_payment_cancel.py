from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.schema import (
    AuditEvent,
    CashTransaction,
    CashTransactionType,
    Counterparty,
    PaymentMethod,
    Sale,
)
from app.services.sales import cancel_client_payment, repay_client_debt


async def _client_with_debts(session):
    client = Counterparty(name="Клиент", phone="1", current_debt=Decimal("700"))
    session.add(client)
    await session.flush()
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    first = Sale(counterparty_id=client.id, total_amount=Decimal("400"), paid_amount=Decimal("0"),
                 debt_amount=Decimal("400"), payment_method="CASH", created_at=base)
    second = Sale(counterparty_id=client.id, total_amount=Decimal("300"), paid_amount=Decimal("0"),
                  debt_amount=Decimal("300"), payment_method="CASH", created_at=base + timedelta(days=1))
    session.add_all([first, second])
    await session.flush()
    return client, first, second


@pytest.mark.asyncio
async def test_double_click_payment_is_rejected(session):
    client, _, _ = await _client_with_debts(session)
    await repay_client_debt(session, client.id, Decimal("201.20"), PaymentMethod.CASH)
    with pytest.raises(ValueError, match="уже принята"):
        await repay_client_debt(session, client.id, Decimal("201.20"), PaymentMethod.CASH)
    # A different amount is a genuine second payment and is accepted.
    await repay_client_debt(session, client.id, Decimal("50"), PaymentMethod.CASH)


@pytest.mark.asyncio
async def test_cancel_payment_restores_debt_on_the_same_sales(session):
    client, first, second = await _client_with_debts(session)
    result = await repay_client_debt(session, client.id, Decimal("450"), PaymentMethod.CASH)
    assert (first.debt_amount, second.debt_amount) == (Decimal("0"), Decimal("250"))

    cancelled = await cancel_client_payment(session, result["payment_id"], "двойное нажатие")

    assert (first.paid_amount, first.debt_amount) == (Decimal("0"), Decimal("400"))
    assert (second.paid_amount, second.debt_amount) == (Decimal("0"), Decimal("300"))
    assert cancelled["sales_debt"] == Decimal("700")
    assert await session.get(CashTransaction, result["payment_id"]) is None
    actions = (await session.execute(
        select(AuditEvent.action).where(AuditEvent.entity_type == "payment").order_by(AuditEvent.id)
    )).scalars().all()
    assert actions == ["CREATED", "CANCELLED"]


@pytest.mark.asyncio
async def test_cancel_legacy_payment_without_allocation_record(session):
    client, first, second = await _client_with_debts(session)
    # A payment made by the old version: sales already updated, no allocation stored.
    first.paid_amount, first.debt_amount = Decimal("400"), Decimal("0")
    second.paid_amount, second.debt_amount = Decimal("100"), Decimal("200")
    payment = CashTransaction(type=CashTransactionType.INCOME, amount=Decimal("150"),
                              payment_method=PaymentMethod.CASH, counterparty_id=client.id,
                              description="Погашение долга",
                              created_at=datetime(2026, 10, 5, tzinfo=timezone.utc))
    session.add(payment)
    await session.flush()

    result = await cancel_client_payment(session, payment.id, "дубль")

    # Taken back from the newest sale first, then the older one.
    assert (second.paid_amount, second.debt_amount) == (Decimal("0"), Decimal("300"))
    assert (first.paid_amount, first.debt_amount) == (Decimal("350"), Decimal("50"))
    assert result["sales_debt"] == Decimal("350")


@pytest.mark.asyncio
async def test_checkout_cash_cannot_be_cancelled_as_repayment(session):
    client, _, _ = await _client_with_debts(session)
    payment = CashTransaction(type=CashTransactionType.INCOME, amount=Decimal("10"),
                              payment_method=PaymentMethod.CASH, counterparty_id=client.id,
                              description="Sale payment")
    session.add(payment)
    await session.flush()
    with pytest.raises(ValueError, match="только погашение"):
        await cancel_client_payment(session, payment.id, "ошибка")
