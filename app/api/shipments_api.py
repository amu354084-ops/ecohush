from __future__ import annotations

from decimal import Decimal
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth_dependencies import require_section
from app.db import async_session
from app.models.schema import Counterparty, Item, Shipment, ShipmentItem
from app.services.shipments import create_shipment, export_shipment_excel
from app.services.localization import display_label


class ShipmentItemInput(BaseModel):
    item_id: int = Field(gt=0)
    qty: Decimal = Field(gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    discount_percent: Decimal = Field(default=Decimal(0), ge=0, le=100)


class ShipmentCreateRequest(BaseModel):
    warehouse_id: int = Field(gt=0)
    recipient_id: int = Field(gt=0)
    items: list[ShipmentItemInput] = Field(min_length=1)
    note: str | None = None


class ShipmentCreateResponse(BaseModel):
    shipment_id: int
    status: str


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


session_dependency = Depends(get_session)
router = APIRouter(dependencies=[Depends(require_section("shipments"))])


@router.post("/create", response_model=ShipmentCreateResponse)
async def create(request: ShipmentCreateRequest, session: AsyncSession = session_dependency) -> ShipmentCreateResponse:
    recipient = await session.get(Counterparty, request.recipient_id)
    if recipient is None:
        raise HTTPException(status_code=400, detail="Получатель не найден")
    # create_shipment performs its own DB operations; commit explicitly to avoid
    # nested transaction errors on some AsyncSession setups
    shipment = await create_shipment(
        session=session,
        warehouse_id=request.warehouse_id,
        recipient_name=recipient.name,
        items=[item.dict() for item in request.items],
        note=request.note,
    )
    await session.commit()
    return ShipmentCreateResponse(shipment_id=shipment.id, status=display_label(shipment.status))


@router.get("/{shipment_id}/invoice")
async def download_invoice(shipment_id: int, session: AsyncSession = session_dependency):
    data, filename, media_type = await export_shipment_excel(session=session, shipment_id=shipment_id)
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/")
async def list_shipments(
    limit: int = 10,
    offset: int = 0,
    q: str | None = None,
    session: AsyncSession = session_dependency,
):
    stmt = (
        select(Shipment)
        .order_by(Shipment.created_at.desc(), Shipment.id.desc())
        .limit(max(1, min(limit, 100)))
        .offset(max(0, offset))
    )
    if q and q.strip():
        stmt = stmt.where(Shipment.recipient_name.ilike(f"%{q.strip()}%"))
    result = await session.execute(stmt)
    shipments = result.scalars().all()
    return [
        {
            "id": shipment.id,
            "recipient_name": shipment.recipient_name,
            "status": display_label(shipment.status),
            "created_at": shipment.created_at.isoformat() if shipment.created_at else None,
            "total_amount": str(shipment.total_amount) if shipment.total_amount is not None else None,
        }
        for shipment in shipments
    ]


@router.get("/{shipment_id}")
async def shipment_details(shipment_id: int, session: AsyncSession = session_dependency):
    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Отгрузка не найдена")
    result = await session.execute(
        select(ShipmentItem, Item)
        .join(Item, Item.id == ShipmentItem.item_id)
        .where(ShipmentItem.shipment_id == shipment_id)
    )
    return {
        "id": shipment.id,
        "recipient_name": shipment.recipient_name,
        "status": display_label(shipment.status),
        "created_at": shipment.created_at.isoformat() if shipment.created_at else None,
        "note": shipment.note or "",
        "total_amount": str(shipment.total_amount or 0),
        "items": [
            {
                "code": item.code,
                "name": item.name,
                "qty": str(shipment_item.qty),
                "unit_price": str(shipment_item.unit_price or 0),
                "discount_percent": str(shipment_item.discount_percent or 0),
            }
            for shipment_item, item in result
        ],
    }
