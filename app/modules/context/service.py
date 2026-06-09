import uuid
from datetime import date

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.context import repository as repo
from app.modules.context.models import ContextEntry
from app.modules.context.schemas import ContextEntryCreate, ContextEntryUpdate

log = structlog.get_logger()


async def create_entry(
    db: AsyncSession, user_id: uuid.UUID, data: ContextEntryCreate
) -> ContextEntry:
    entry = await repo.create_entry(
        db,
        user_id=user_id,
        entry_date=data.date,
        energy_level=data.energy_level,
        mood=data.mood,
        notes=data.notes,
        event_id=data.event_id,
    )
    log.info("context.created", user_id=str(user_id), entry_id=str(entry.id))
    return entry


async def list_entries(
    db: AsyncSession,
    user_id: uuid.UUID,
    start_date: date | None,
    end_date: date | None,
) -> list[ContextEntry]:
    return await repo.list_entries(db, user_id, start_date, end_date)


async def get_entry(
    db: AsyncSession, user_id: uuid.UUID, entry_id: uuid.UUID
) -> ContextEntry:
    entry = await repo.get_entry(db, entry_id, user_id)
    if not entry:
        raise AppException(404, "Context entry not found")
    return entry


async def update_entry(
    db: AsyncSession, user_id: uuid.UUID, entry_id: uuid.UUID, data: ContextEntryUpdate
) -> ContextEntry:
    entry = await repo.get_entry(db, entry_id, user_id)
    if not entry:
        raise AppException(404, "Context entry not found")
    updated = await repo.update_entry(
        db,
        entry_id,
        user_id,
        **{k: v for k, v in data.model_dump(exclude_unset=True).items()},
    )
    return updated  # type: ignore[return-value]


async def delete_entry(
    db: AsyncSession, user_id: uuid.UUID, entry_id: uuid.UUID
) -> None:
    deleted = await repo.delete_entry(db, entry_id, user_id)
    if not deleted:
        raise AppException(404, "Context entry not found")
    log.info("context.deleted", user_id=str(user_id), entry_id=str(entry_id))
