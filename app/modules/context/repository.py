import uuid
from datetime import date

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.context.models import ContextEntry


async def create_entry(
    db: AsyncSession,
    user_id: uuid.UUID,
    entry_date: date,
    energy_level: int,
    mood: int,
    notes: str | None,
    event_id: uuid.UUID | None,
) -> ContextEntry:
    entry = ContextEntry(
        user_id=user_id,
        date=entry_date,
        energy_level=energy_level,
        mood=mood,
        notes=notes,
        event_id=event_id,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


async def get_entry(
    db: AsyncSession, entry_id: uuid.UUID, user_id: uuid.UUID
) -> ContextEntry | None:
    result = await db.execute(
        select(ContextEntry).where(
            ContextEntry.id == entry_id, ContextEntry.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def list_entries(
    db: AsyncSession,
    user_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[ContextEntry]:
    q = select(ContextEntry).where(ContextEntry.user_id == user_id)
    if start_date:
        q = q.where(ContextEntry.date >= start_date)
    if end_date:
        q = q.where(ContextEntry.date <= end_date)
    q = q.order_by(ContextEntry.date.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_entry(
    db: AsyncSession,
    entry_id: uuid.UUID,
    user_id: uuid.UUID,
    **fields: object,
) -> ContextEntry | None:
    filtered = {k: v for k, v in fields.items() if v is not None}
    if not filtered:
        return await get_entry(db, entry_id, user_id)
    result = await db.execute(
        update(ContextEntry)
        .where(ContextEntry.id == entry_id, ContextEntry.user_id == user_id)
        .values(**filtered)
        .returning(ContextEntry)
    )
    await db.flush()
    return result.scalar_one_or_none()


async def delete_entry(
    db: AsyncSession, entry_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    result = await db.execute(
        delete(ContextEntry).where(
            ContextEntry.id == entry_id, ContextEntry.user_id == user_id
        )
    )
    return result.rowcount > 0
