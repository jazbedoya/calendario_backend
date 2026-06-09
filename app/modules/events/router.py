import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.events import service
from app.modules.events.schemas import EventCreate, EventOut, EventUpdate

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventOut, status_code=201)
async def create_event(
    data: EventCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventOut:
    event = await service.create_event(db, current_user.id, data)
    return EventOut.model_validate(event)


@router.get("", response_model=list[EventOut])
async def list_events(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    layer: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EventOut]:
    events = await service.list_events(db, current_user.id, start, end, layer)
    return [EventOut.model_validate(e) for e in events]


@router.get("/{event_id}", response_model=EventOut)
async def get_event(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventOut:
    event = await service.get_event(db, current_user.id, event_id)
    return EventOut.model_validate(event)


@router.put("/{event_id}", response_model=EventOut)
async def update_event(
    event_id: uuid.UUID,
    data: EventUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventOut:
    event = await service.update_event(db, current_user.id, event_id, data)
    return EventOut.model_validate(event)


@router.delete("/{event_id}", status_code=204)
async def delete_event(
    event_id: uuid.UUID,
    delete_mode: str = Query(default="single", pattern="^(single|all)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.delete_event(db, current_user.id, event_id, delete_mode=delete_mode)


@router.post("/{event_id}/restore", response_model=EventOut)
async def restore_event(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventOut:
    event = await service.restore_event(db, current_user.id, event_id)
    return EventOut.model_validate(event)
