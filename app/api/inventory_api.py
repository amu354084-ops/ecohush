from __future__ import annotations

from datetime import date, datetime, time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import async_session
from app.models.schema import BOMHeader, BOMItem, Batch, Item, ItemType, OrderItem, SaleItem, ShipmentItem, User, Warehouse
from pydantic import Field
from decimal import Decimal
from app.services.inventory import create_batch
from app.services.localization import display_label
from app.api.auth_dependencies import require_roles, require_section


class CreateBatchRequest(BaseModel):
    item_id: int
    warehouse_id: int
    purchase_cost: Decimal = Field(ge=0)
    sale_price: Decimal = Field(ge=0)
    qty: Decimal = Field(gt=0)


class UpdateBatchPricesRequest(BaseModel):
    purchase_cost: Decimal = Field(ge=0)
    sale_price: Decimal = Field(ge=0)


class WarehouseResponse(BaseModel):
    id: int
    name: str
    description: str


class CreateItemRequest(BaseModel):
    code: str
    name: str
    type: ItemType
    unit: str
    min_stock: int = Field(ge=0)
    price: Decimal = Field(default=Decimal(0), ge=0)


class UpdateItemPriceRequest(BaseModel):
    price: Decimal = Field(ge=0)


class ItemResponse(BaseModel):
    id: int
    code: str
    name: str
    type: str
    type_code: str
    unit: str
    min_stock: int
    price: str


class BatchResponse(BaseModel):
    id: int
    item_id: int
    warehouse_id: int
    purchase_cost: str
    sale_price: str
    initial_qty: str
    remaining_qty: str
    created_at: str


class BOMItemResponse(BaseModel):
    component_id: int
    quantity: str
    scrap_rate_percent: str


class BOMResponse(BaseModel):
    id: int
    product_id: int
    name: str
    is_active: bool
    components: list[BOMItemResponse]


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


session_dependency = Depends(get_session)
router = APIRouter(dependencies=[Depends(require_section("warehouse"))])


@router.get("/warehouses", response_model=list[WarehouseResponse])
async def read_warehouses(_: User = Depends(require_section("warehouse")), session: AsyncSession = session_dependency) -> list[WarehouseResponse]:
    result = await session.execute(select(Warehouse))
    warehouses = result.scalars().all()
    return [WarehouseResponse(id=w.id, name=w.name, description=w.description or "") for w in warehouses]


@router.get("/items", response_model=list[ItemResponse])
async def read_items(_: User = Depends(require_section("warehouse")), session: AsyncSession = session_dependency) -> list[ItemResponse]:
    result = await session.execute(select(Item))
    items = result.scalars().all()
    return [
        ItemResponse(
            id=i.id,
            code=i.code,
            name=i.name,
            type=display_label(i.type.value),
            type_code=i.type.value,
            unit=i.unit,
            min_stock=i.min_stock,
            price=str(i.price),
        )
        for i in items
    ]


@router.post("/items", response_model=ItemResponse)
async def create_item(request: CreateItemRequest, session: AsyncSession = session_dependency) -> ItemResponse:
    existing = await session.execute(select(Item).where(Item.code == request.code))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Товар с таким кодом уже существует")
    item = Item(
        code=request.code,
        name=request.name,
        type=request.type,
        unit=request.unit,
        min_stock=request.min_stock,
        price=request.price,
    )
    session.add(item)
    await session.flush()
    await session.commit()
    await session.refresh(item)
    return ItemResponse(
        id=item.id,
        code=item.code,
        name=item.name,
        type=display_label(item.type.value),
        type_code=item.type.value,
        unit=item.unit,
        min_stock=item.min_stock,
        price=str(item.price),
    )


@router.patch("/items/{item_id}/price", response_model=ItemResponse, dependencies=[Depends(require_roles("ADMIN"))])
async def update_item_price(
    item_id: int,
    request: UpdateItemPriceRequest,
    session: AsyncSession = session_dependency,
) -> ItemResponse:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Товар не найден")
    item.price = request.price
    await session.commit()
    await session.refresh(item)
    return ItemResponse(
        id=item.id, code=item.code, name=item.name,
        type=display_label(item.type.value), type_code=item.type.value,
        unit=item.unit, min_stock=item.min_stock, price=str(item.price),
    )


@router.delete("/items/{item_id}", status_code=204, dependencies=[Depends(require_roles("ADMIN"))])
async def delete_item(item_id: int, session: AsyncSession = session_dependency) -> Response:
    item = await session.get(Item, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Товар не найден")

    references = (
        (BOMHeader, BOMHeader.product_id),
        (BOMItem, BOMItem.component_id),
        (Batch, Batch.item_id),
        (OrderItem, OrderItem.item_id),
        (SaleItem, SaleItem.item_id),
        (ShipmentItem, ShipmentItem.item_id),
    )
    for model, column in references:
        if await session.scalar(select(model.id).where(column == item_id).limit(1)) is not None:
            raise HTTPException(
                status_code=409,
                detail="Нельзя удалить товар, который уже используется в операциях или формулах",
            )

    await session.delete(item)
    await session.commit()
    return Response(status_code=204)


@router.get("/batches", response_model=list[BatchResponse])
async def read_batches(
    limit: int = 500,
    offset: int = 0,
    session: AsyncSession = session_dependency,
) -> list[BatchResponse]:
    result = await session.execute(
        select(Batch)
        .order_by(Batch.created_at.desc(), Batch.id.desc())
        .limit(max(1, min(limit, 5000)))
        .offset(max(0, offset))
    )
    batches = result.scalars().all()
    return [
        BatchResponse(
            id=b.id,
            item_id=b.item_id,
            warehouse_id=b.warehouse_id,
            purchase_cost=str(b.purchase_cost),
            sale_price=str(b.sale_price),
            initial_qty=str(b.initial_qty),
            remaining_qty=str(b.remaining_qty),
            created_at=b.created_at.isoformat(),
        )
        for b in batches
    ]


@router.patch(
    "/batches/{batch_id}/prices",
    response_model=BatchResponse,
    dependencies=[Depends(require_roles("ADMIN"))],
)
async def update_batch_prices(
    batch_id: int,
    request: UpdateBatchPricesRequest,
    session: AsyncSession = session_dependency,
) -> BatchResponse:
    batch = await session.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Партия не найдена")
    batch.purchase_cost = request.purchase_cost
    batch.sale_price = request.sale_price
    await session.commit()
    await session.refresh(batch)
    return BatchResponse(
        id=batch.id,
        item_id=batch.item_id,
        warehouse_id=batch.warehouse_id,
        purchase_cost=str(batch.purchase_cost),
        sale_price=str(batch.sale_price),
        initial_qty=str(batch.initial_qty),
        remaining_qty=str(batch.remaining_qty),
        created_at=batch.created_at.isoformat(),
    )


@router.get("/boms", response_model=list[BOMResponse])
async def read_boms(session: AsyncSession = session_dependency) -> list[BOMResponse]:
    result = await session.execute(
        select(BOMHeader).options(selectinload(BOMHeader.bom_items))
    )
    boms = result.scalars().all()
    return [
        BOMResponse(
            id=b.id,
            product_id=b.product_id,
            name=b.name,
            is_active=b.is_active,
            components=[
                BOMItemResponse(
                    component_id=item.component_id,
                    quantity=str(item.quantity),
                    scrap_rate_percent=str(item.scrap_rate_percent),
                )
                for item in b.bom_items
            ],
        )
        for b in boms
    ]


@router.post("/batches", response_model=BatchResponse)
async def create_batch_endpoint(
    request: CreateBatchRequest,
    session: AsyncSession = session_dependency,
) -> BatchResponse:
    async with session.begin():
        batch = await create_batch(
            session=session,
            item_id=request.item_id,
            warehouse_id=request.warehouse_id,
            purchase_cost=request.purchase_cost,
            qty=request.qty,
            sale_price=request.sale_price,
        )
    return BatchResponse(
        id=batch.id,
        item_id=batch.item_id,
        warehouse_id=batch.warehouse_id,
        purchase_cost=str(batch.purchase_cost),
        sale_price=str(batch.sale_price),
        initial_qty=str(batch.initial_qty),
        remaining_qty=str(batch.remaining_qty),
        created_at=batch.created_at.isoformat(),
    )


class StockSummaryResponse(BaseModel):
    item_id: int
    item_code: str
    item_name: str
    unit: str
    warehouse_id: int
    warehouse_name: str
    remaining_qty: str


class StockHistoryResponse(BaseModel):
    id: int
    timestamp: str
    warehouse_name: str
    item_code: str
    item_name: str
    unit: str
    operation: str
    qty: str
    comment: str


@router.get("/stock_summary", response_model=list[StockSummaryResponse])
async def read_stock_summary(
    warehouse_id: int | None = None,
    session: AsyncSession = session_dependency,
) -> list[StockSummaryResponse]:
    from app.services.inventory import get_stock_summary

    rows = await get_stock_summary(session=session, warehouse_id=warehouse_id)
    return [StockSummaryResponse(**row) for row in rows]


@router.get("/stock_summary/export")
async def export_stock_summary(
    warehouse_id: int | None = None,
    _: User = Depends(require_roles("ADMIN")),
    session: AsyncSession = session_dependency,
):
    from app.services.inventory import export_stock_summary_excel

    data, filename, media_type = await export_stock_summary_excel(
        session=session,
        warehouse_id=warehouse_id,
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/stock_history", response_model=list[StockHistoryResponse])
async def read_stock_history(
    warehouse_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 500,
    offset: int = 0,
    session: AsyncSession = session_dependency,
) -> list[StockHistoryResponse]:
    from app.services.inventory import get_stock_history

    rows = await get_stock_history(
        session=session,
        warehouse_id=warehouse_id,
        date_from=datetime.combine(date_from, time.min) if date_from else None,
        date_to=datetime.combine(date_to, time.max) if date_to else None,
        limit=max(1, min(limit, 5000)),
        offset=max(0, offset),
    )
    return [StockHistoryResponse(**row) for row in rows]


@router.get("/stock_history/export")
async def export_stock_history(
    warehouse_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    _: User = Depends(require_roles("ADMIN")),
    session: AsyncSession = session_dependency,
):
    from app.services.inventory import export_stock_history_excel

    data, filename, media_type = await export_stock_history_excel(
        session=session,
        warehouse_id=warehouse_id,
        date_from=datetime.combine(date_from, time.min) if date_from else None,
        date_to=datetime.combine(date_to, time.max) if date_to else None,
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
