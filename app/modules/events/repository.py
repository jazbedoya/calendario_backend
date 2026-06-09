import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event


async def create_event(
    db: AsyncSession,
    user_id: uuid.UUID,
    title: str,
    description: str | None,
    start_at: datetime,
    end_at: datetime,
    is_all_day: bool,
    location: str | None,
    layer: str,
    source: str = "manual",
    google_event_id: str | None = None,
    recurrence_rule: str | None = None,
    recurrence_parent_id: uuid.UUID | None = None,
) -> Event:
    event = Event(
        user_id=user_id,
        title=title,
        description=description,
        start_at=start_at,
        end_at=end_at,
        is_all_day=is_all_day,
        location=location,
        layer=layer,
        source=source,
        google_event_id=google_event_id,
        recurrence_rule=recurrence_rule,
        recurrence_parent_id=recurrence_parent_id,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return event


async def get_event(
    db: AsyncSession, event_id: uuid.UUID, user_id: uuid.UUID
) -> Event | None:
    result = await db.execute(
        select(Event).where(
            Event.id == event_id,
            Event.user_id == user_id,
            Event.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def list_events(
    db: AsyncSession,
    user_id: uuid.UUID,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    layer: str | None = None,
) -> list[Event]:
    q = select(Event).where(Event.user_id == user_id, Event.deleted_at.is_(None))
    if start_at:
        q = q.where(Event.start_at >= start_at)
    if end_at:
        q = q.where(Event.start_at <= end_at)
    if layer:
        q = q.where(Event.layer == layer)
    q = q.order_by(Event.start_at)
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_event(
    db: AsyncSession,
    event_id: uuid.UUID,
    user_id: uuid.UUID,
    **fields: object,
) -> Event | None:
    filtered = {k: v for k, v in fields.items() if v is not None}
    if not filtered:
        return await get_event(db, event_id, user_id)
    await db.execute(
        update(Event)
        .where(Event.id == event_id, Event.user_id == user_id)
        .values(**filtered)
    )
    await db.flush()
    return await get_event(db, event_id, user_id)


async def delete_event(
    db: AsyncSession, event_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    """Soft-delete: sets deleted_at = now(). Returns False if event not found or already deleted."""
    result = await db.execute(
        update(Event)
        .where(Event.id == event_id, Event.user_id == user_id, Event.deleted_at.is_(None))
        .values(deleted_at=datetime.now(timezone.utc))
    )
    await db.flush()
    return result.rowcount > 0


async def delete_recurring_series(
    db: AsyncSession, event_id: uuid.UUID, user_id: uuid.UUID
) -> int:
    """Soft-delete all events in the same recurrence series.

    Resolves the series root (event itself if parent, or its recurrence_parent_id),
    then deletes all events sharing that root.
    Returns number of rows affected.
    """
    # Find the event to determine the series root
    event = await get_event(db, event_id, user_id)
    if not event:
        return 0
    root_id = event.recurrence_parent_id if event.recurrence_parent_id else event.id
    result = await db.execute(
        update(Event)
        .where(
            Event.user_id == user_id,
            Event.deleted_at.is_(None),
            or_(Event.id == root_id, Event.recurrence_parent_id == root_id),
        )
        .values(deleted_at=datetime.now(timezone.utc))
    )
    await db.flush()
    return result.rowcount


async def restore_event(
    db: AsyncSession, event_id: uuid.UUID, user_id: uuid.UUID
) -> Event | None:
    """Undo soft-delete. Returns the restored event, or None if not found / not deleted."""
    result = await db.execute(
        update(Event)
        .where(Event.id == event_id, Event.user_id == user_id, Event.deleted_at.is_not(None))
        .values(deleted_at=None)
        .returning(Event)
    )
    await db.flush()
    row = result.scalar_one_or_none()
    if row:
        await db.refresh(row)
    return row
