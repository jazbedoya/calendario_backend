import calendar
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.events import repository as repo
from app.modules.events.models import Event
from app.modules.events.schemas import EventCreate, EventUpdate

log = structlog.get_logger()

# Number of occurrences to generate per recurrence type
_RECURRENCE_COUNTS: dict[str, int] = {
    "daily":   90,   # ~3 months
    "weekly":  52,   # 1 year
    "monthly": 12,   # 1 year
}


def _add_months(dt: datetime, months: int) -> datetime:
    """Add N months to a datetime, clamping day to the last day of the target month."""
    total_months = dt.month - 1 + months
    year = dt.year + total_months // 12
    month = total_months % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _offset_dt(dt: datetime, rule: str, n: int) -> datetime:
    if rule == "daily":
        return dt + timedelta(days=n)
    if rule == "weekly":
        return dt + timedelta(weeks=n)
    # monthly
    return _add_months(dt, n)


async def create_event(db: AsyncSession, user_id: uuid.UUID, data: EventCreate) -> Event:
    if data.end_at <= data.start_at:
        raise AppException(400, "end_at must be after start_at")

    event = await repo.create_event(
        db,
        user_id=user_id,
        title=data.title,
        description=data.description,
        start_at=data.start_at,
        end_at=data.end_at,
        is_all_day=data.is_all_day,
        location=data.location,
        layer=data.layer,
        recurrence_rule=data.recurrence_rule,
    )

    if data.recurrence_rule:
        count = _RECURRENCE_COUNTS.get(data.recurrence_rule, 12)
        duration = data.end_at - data.start_at
        for i in range(1, count + 1):
            occ_start = _offset_dt(data.start_at, data.recurrence_rule, i)
            occ_end   = occ_start + duration
            await repo.create_event(
                db,
                user_id=user_id,
                title=data.title,
                description=data.description,
                start_at=occ_start,
                end_at=occ_end,
                is_all_day=data.is_all_day,
                location=data.location,
                layer=data.layer,
                recurrence_rule=data.recurrence_rule,
                recurrence_parent_id=event.id,
            )
        log.info(
            "event.recurrence_created",
            user_id=str(user_id),
            event_id=str(event.id),
            rule=data.recurrence_rule,
            count=count,
        )
    else:
        log.info("event.created", user_id=str(user_id), event_id=str(event.id))

    return event


async def list_events(
    db: AsyncSession,
    user_id: uuid.UUID,
    start_at: datetime | None,
    end_at: datetime | None,
    layer: str | None,
) -> list[Event]:
    return await repo.list_events(db, user_id, start_at, end_at, layer)


async def get_event(db: AsyncSession, user_id: uuid.UUID, event_id: uuid.UUID) -> Event:
    event = await repo.get_event(db, event_id, user_id)
    if not event:
        raise AppException(404, "Event not found")
    return event


async def update_event(
    db: AsyncSession, user_id: uuid.UUID, event_id: uuid.UUID, data: EventUpdate
) -> Event:
    event = await repo.get_event(db, event_id, user_id)
    if not event:
        raise AppException(404, "Event not found")
    if data.start_at and data.end_at and data.end_at <= data.start_at:
        raise AppException(400, "end_at must be after start_at")
    updated = await repo.update_event(
        db,
        event_id,
        user_id,
        **{k: v for k, v in data.model_dump(exclude_unset=True).items()},
    )
    return updated  # type: ignore[return-value]


async def delete_event(
    db: AsyncSession,
    user_id: uuid.UUID,
    event_id: uuid.UUID,
    delete_mode: str = "single",
) -> None:
    if delete_mode == "all":
        count = await repo.delete_recurring_series(db, event_id, user_id)
        if count == 0:
            raise AppException(404, "Event not found")
        log.info("event.series_deleted", user_id=str(user_id), event_id=str(event_id), count=count)
    else:
        deleted = await repo.delete_event(db, event_id, user_id)
        if not deleted:
            raise AppException(404, "Event not found")
        log.info("event.deleted", user_id=str(user_id), event_id=str(event_id))


async def restore_event(
    db: AsyncSession, user_id: uuid.UUID, event_id: uuid.UUID
) -> Event:
    event = await repo.restore_event(db, event_id, user_id)
    if not event:
        raise AppException(404, "Event not found or not deleted")
    log.info("event.restored", user_id=str(user_id), event_id=str(event_id))
    return event
