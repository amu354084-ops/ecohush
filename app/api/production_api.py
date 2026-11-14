from __future__ import annotations

from decimal import Decimal
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import current_user, require_section, user_permissions
from app.db import async_session
from app.models.schema import Order, ProductionOrderStatus, User
from app.services.production import (
    complete_production_order,
    create_production_order,
    execute_production,
    process_return,
)


class ProductionRunRequest(BaseModel):
    bom_id: int
    output_qty: Decimal = Field(gt=0)
    additional_overheads: Decimal = Field(ge=0)
    actual_waste: dict[int, Decimal] = Field(default_factory=dict)

    @field_validator("actual_waste", mode="before")
    def normalize_waste(cls, value: dict[int, Any]) -> dict[int, Decimal]:
        return {int(k): Decimal(v) for k, v in value.items()}


class ProductionRunResponse(BaseModel):
    bom_id: int
    product_id: int
    output_qty: Decimal
    unit_cost: Decimal
    raw_cost_total: Decimal
    additional_overheads: Decimal
    batch_usages: list[dict[str, Any]]
    scrap_entries: list[dict[str, Any]]


class ReturnRequest(BaseModel):
    sale_id: int
    defective: bool
    comment: str = Field(min_length=1)


class ReturnResponse(BaseModel):
    sale_id: int
    refund_amount: Decimal
    defective: bool


class ProductionOrderRequest(BaseModel):
    batch_number: str = Field(min_length=1, max_length=64)
    bom_id: int = Field(gt=0)
    planned_qty: Decimal = Field(gt=0)


class ProductionCompleteRequest(BaseModel):
    actual_qty: Decimal = Field(gt=0)
    additional_overheads: Decimal = Field(default=Decimal(0), ge=0)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


session_dependency = Depends(get_session)
router = APIRouter(dependencies=[Depends(require_section("production"))])


@router.post("/orders")
async def create_order(request: ProductionOrderRequest, session: AsyncSession = session_dependency) -> dict[str, Any]:
    try:
        async with session.begin():
            order = await create_production_order(session, request.batch_number, request.bom_id, request.planned_qty)
        return {"id": order.id, "batch_number": order.batch_number, "status": order.status}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/orders/{order_id}/start")
async def start_order(order_id: int, session: AsyncSession = session_dependency) -> dict[str, Any]:
    from app.models.schema import ProductionOrder

    async with session.begin():
        order = await session.get(ProductionOrder, order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Production order not found")
        if order.status != ProductionOrderStatus.PLANNED:
            raise HTTPException(status_code=400, detail="Only planned orders can be started")
        order.status = ProductionOrderStatus.IN_PROGRESS
    return {"id": order.id, "status": order.status}


@router.post("/orders/{order_id}/complete")
async def complete_order(order_id: int, request: ProductionCompleteRequest, session: AsyncSession = session_dependency) -> dict[str, Any]:
    try:
        async with session.begin():
            return await complete_production_order(session, order_id, request.actual_qty, request.additional_overheads)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/run", response_model=ProductionRunResponse)
async def run_production(
    request: ProductionRunRequest,
    session: AsyncSession = session_dependency,
) -> ProductionRunResponse:
    try:
        async with session.begin():
            result = await execute_production(
                session=session,
                bom_id=request.bom_id,
                output_qty=request.output_qty,
                additional_overheads=request.additional_overheads,
                actual_waste=request.actual_waste,
            )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/return", response_model=ReturnResponse)
async def handle_return(
    request: ReturnRequest,
    user: User = Depends(current_user),
    session: AsyncSession = session_dependency,
) -> ReturnResponse:
    if user.role != "ADMIN" and "orders_edit_delivered" not in user_permissions(user):
        raise HTTPException(status_code=403, detail="Нет права оформлять возвраты")
    try:
        async with session.begin():
            linked_order_id = await session.scalar(select(Order.id).where(Order.sale_id == request.sale_id).limit(1))
            if linked_order_id is not None:
                raise ValueError(
                    f"Эта продажа создана из заявки №{linked_order_id}. "
                    "Измените или удалите заявку — товар и деньги вернутся автоматически"
                )
            result = await process_return(
                session=session,
                sale_id=request.sale_id,
                defective=request.defective,
                comment=request.comment,
            )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
