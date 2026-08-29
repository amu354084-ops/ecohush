from __future__ import annotations

from decimal import Decimal
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.auth_dependencies import require_section
from app.db import async_session
from app.models.schema import PaymentMethod, Sale, SaleItem
from app.services.invoice import sale_invoice_html
from app.services.sales import checkout_sale


class SaleItemInput(BaseModel):
    item_id: int = Field(gt=0)
    qty: Decimal = Field(gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    discount_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class CheckoutResponseItem(BaseModel):
    item_id: int
    qty: Decimal
    unit_price: Decimal
    cost_price: Decimal
    discount_percent: Decimal


class CheckoutResponse(BaseModel):
    sale_id: int
    total_amount: Decimal
    paid_amount: Decimal
    debt_amount: Decimal
    items: list[CheckoutResponseItem]
    batch_details: list[dict[str, Any]]


class CheckoutRequest(BaseModel):
    counterparty_id: int | None = None
    items: list[SaleItemInput] = Field(min_length=1)
    paid_amount: Decimal = Field(ge=0)
    payment_method: PaymentMethod | str = PaymentMethod.CASH

    @field_validator("payment_method", mode="before")
    def normalize_payment_method(cls, value: PaymentMethod | str) -> PaymentMethod:
        if isinstance(value, PaymentMethod):
            return value

        normalized = str(value).strip().upper().replace("-", "_")
        supported = {
            "CASH": PaymentMethod.CASH,
            "BANK": PaymentMethod.BANK,
            "CARD": PaymentMethod.CARD,
            "BANK_TRANSFER": PaymentMethod.BANK_TRANSFER,
        }
        if normalized in supported:
            return supported[normalized]
        raise ValueError("Unsupported payment method: supported values are CASH, BANK, CARD, BANK_TRANSFER")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


session_dependency = Depends(get_session)
router = APIRouter(dependencies=[Depends(require_section("sales"))])


@router.get("/{sale_id}/invoice", response_class=HTMLResponse)
async def sale_invoice(sale_id: int, session: AsyncSession = session_dependency) -> HTMLResponse:
    sale = await session.scalar(
        select(Sale).options(
            selectinload(Sale.counterparty),
            selectinload(Sale.sale_items).selectinload(SaleItem.item),
        ).where(Sale.id == sale_id)
    )
    if sale is None:
        raise HTTPException(status_code=404, detail="Продажа не найдена")
    return HTMLResponse(sale_invoice_html(sale))


@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(request: CheckoutRequest, session: AsyncSession = session_dependency) -> CheckoutResponse:
    try:
        async with session.begin():
            result = await checkout_sale(
                session=session,
                counterparty_id=request.counterparty_id,
                items=[item.dict() for item in request.items],
                paid_amount=request.paid_amount,
                payment_method=request.payment_method,
            )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
