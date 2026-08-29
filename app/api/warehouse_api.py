from __future__ import annotations

from decimal import Decimal
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.services.inventory import adjust_stock
from app.services.warehouse_ops import add_stock, move_stock
from app.api.auth_dependencies import require_section


class WarehouseOperationRequest(BaseModel):
    item_id: int
    warehouse_id: int
    qty: Decimal = Field(gt=0)
    cost: Decimal = Field(ge=0)
    comment: str | None = None


class WarehouseMoveRequest(BaseModel):
    item_id: int
    from_warehouse_id: int
    to_warehouse_id: int
    qty: Decimal = Field(gt=0)
    cost: Decimal | None = Field(default=None, ge=0)
    sale_price: Decimal | None = Field(default=None, ge=0)
    comment: str | None = None


class WarehouseAdjustmentRequest(BaseModel):
    item_id: int
    warehouse_id: int
    delta_qty: Decimal
    cost: Decimal | None = Field(default=None, ge=0)
    comment: str | None = None


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


session_dependency = Depends(get_session)
router = APIRouter(dependencies=[Depends(require_section("warehouse"))])


@router.post("/incoming")
async def incoming(request: WarehouseOperationRequest, session: AsyncSession = session_dependency) -> dict[str, Any]:
    try:
        async with session.begin():
            batch = await add_stock(
                session,
                request.item_id,
                request.warehouse_id,
                request.qty,
                request.cost,
                request.comment,
                sale_price=request.sale_price,
            )
        return {"batch_id": batch.id, "remaining_qty": str(batch.remaining_qty)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/move")
async def move(request: WarehouseMoveRequest, session: AsyncSession = session_dependency) -> dict[str, Any]:
    try:
        async with session.begin():
            result = await move_stock(
                session,
                request.item_id,
                request.from_warehouse_id,
                request.to_warehouse_id,
                request.qty,
                request.comment,
                request.cost,
            )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/adjust")
async def adjust(request: WarehouseAdjustmentRequest, session: AsyncSession = session_dependency) -> dict[str, Any]:
    try:
        async with session.begin():
            result = await adjust_stock(
                session=session,
                item_id=request.item_id,
                warehouse_id=request.warehouse_id,
                delta_qty=request.delta_qty,
                comment=request.comment,
                unit_cost=request.cost,
            )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
