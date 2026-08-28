from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from typing import AsyncGenerator

from app.api.auth_dependencies import require_section
from app.db import async_session
from app.services.formulas import create_formula, delete_formula, update_formula


class FormulaComponentInput(BaseModel):
    component_id: int
    quantity: float = Field(gt=0)
    scrap_rate_percent: float = Field(default=0)


class CreateFormulaRequest(BaseModel):
    product_id: int = Field(gt=0)
    name: str = Field(min_length=1)
    components: list[FormulaComponentInput] = Field(min_length=1)


class UpdateFormulaRequest(CreateFormulaRequest):
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


session_dependency = Depends(get_session)
router = APIRouter(dependencies=[Depends(require_section("formula"))])


@router.post("/create")
async def create_formula_endpoint(request: CreateFormulaRequest, session: AsyncSession = session_dependency) -> dict:
    bom = await create_formula(
        session=session,
        product_id=request.product_id,
        name=request.name,
        components=[component.dict() for component in request.components],
    )
    await session.commit()
    return {"bom_id": bom.id, "name": bom.name}


@router.put("/{bom_id}")
async def update_formula_endpoint(
    bom_id: int,
    request: UpdateFormulaRequest,
    session: AsyncSession = session_dependency,
) -> dict:
    try:
        bom = await update_formula(
            session=session,
            bom_id=bom_id,
            product_id=request.product_id,
            name=request.name,
            components=[component.dict() for component in request.components],
        )
        await session.commit()
        return {"bom_id": bom.id, "name": bom.name}
    except ValueError:
        # If the BOM to update was not found, create a new one instead.
        bom = await create_formula(
            session=session,
            product_id=request.product_id,
            name=request.name,
            components=[component.dict() for component in request.components],
        )
        await session.commit()
        return {"bom_id": bom.id, "name": bom.name}


@router.delete("/{bom_id}")
async def delete_formula_endpoint(bom_id: int, session: AsyncSession = session_dependency) -> dict:
    try:
        await delete_formula(session=session, bom_id=bom_id)
        await session.commit()
        return {"bom_id": bom_id, "deleted": True}
    except ValueError as exc:
        await session.rollback()
        return {"detail": str(exc)}
