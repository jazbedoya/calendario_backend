import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.context import service
from app.modules.context.schemas import ContextEntryCreate, ContextEntryOut, ContextEntryUpdate

router = APIRouter(prefix="/context", tags=["context"])


@router.post("", response_model=ContextEntryOut, status_code=201)
async def create_entry(
    data: ContextEntryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContextEntryOut:
    entry = await service.create_entry(db, current_user.id, data)
    return ContextEntryOut.model_validate(entry)


@router.get("", response_model=list[ContextEntryOut])
async def list_entries(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ContextEntryOut]:
    entries = await service.list_entries(db, current_user.id, start, end)
    return [ContextEntryOut.model_validate(e) for e in entries]


@router.get("/{entry_id}", response_model=ContextEntryOut)
async def get_entry(
    entry_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContextEntryOut:
    entry = await service.get_entry(db, current_user.id, entry_id)
    return ContextEntryOut.model_validate(entry)


@router.put("/{entry_id}", response_model=ContextEntryOut)
async def update_entry(
    entry_id: uuid.UUID,
    data: ContextEntryUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContextEntryOut:
    entry = await service.update_entry(db, current_user.id, entry_id, data)
    return ContextEntryOut.model_validate(entry)


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.delete_entry(db, current_user.id, entry_id)
