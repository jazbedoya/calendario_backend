import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.calendar.models import CalendarEvent, GoogleCalendarAccount


async def get_google_account(
    db: AsyncSession, user_id: uuid.UUID
) -> GoogleCalendarAccount | None:
    result = await db.execute(
        select(GoogleCalendarAccount).where(GoogleCalendarAccount.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def save_google_account(
    db: AsyncSession,
    user_id: uuid.UUID,
    google_account_id: str,
    google_email: str,
    access_token_enc: str,
    refresh_token_enc: str,
    token_expiry: datetime | None,
    scopes: str,
) -> GoogleCalendarAccount:
    existing = await get_google_account(db, user_id)
    if existing:
        await db.execute(
            update(GoogleCalendarAccount)
            .where(GoogleCalendarAccount.user_id == user_id)
            .values(
                google_account_id=google_account_id,
                google_email=google_email,
                access_token_enc=access_token_enc,
                refresh_token_enc=refresh_token_enc,
                token_expiry=token_expiry,
                scopes=scopes,
            )
        )
        await db.flush()
        return await get_google_account(db, user_id)  # type: ignore[return-value]

    account = GoogleCalendarAccount(
        user_id=user_id,
        google_account_id=google_account_id,
        google_email=google_email,
        access_token_enc=access_token_enc,
        refresh_token_enc=refresh_token_enc,
        token_expiry=token_expiry,
        scopes=scopes,
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


async def update_google_account_tokens(
    db: AsyncSession,
    user_id: uuid.UUID,
    access_token_enc: str,
    refresh_token_enc: str,
    token_expiry: datetime | None,
) -> None:
    await db.execute(
        update(GoogleCalendarAccount)
        .where(GoogleCalendarAccount.user_id == user_id)
        .values(
            access_token_enc=access_token_enc,
            refresh_token_enc=refresh_token_enc,
            token_expiry=token_expiry,
        )
    )


async def update_last_synced(db: AsyncSession, user_id: uuid.UUID) -> None:
    from datetime import timezone
    await db.execute(
        update(GoogleCalendarAccount)
        .where(GoogleCalendarAccount.user_id == user_id)
        .values(last_synced_at=datetime.now(timezone.utc))
    )
    await db.flush()


async def delete_google_account(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        delete(GoogleCalendarAccount).where(GoogleCalendarAccount.user_id == user_id)
    )


async def upsert_events_batch(
    db: AsyncSession,
    rows: list[dict],
) -> int:
    """Batch upsert calendar events using ON CONFLICT.

    Each dict in `rows` must contain: user_id, google_event_id, calendar_id,
    title, description, start_at, end_at, is_all_day, location.
    Returns number of rows upserted.
    """
    if not rows:
        return 0

    dialect = db.bind.dialect.name if db.bind else "postgresql"  # type: ignore[union-attr]
    _update_set = {
        "calendar_id": "calendar_id",
        "title": "title",
        "description": "description",
        "start_at": "start_at",
        "end_at": "end_at",
        "is_all_day": "is_all_day",
        "location": "location",
    }

    if dialect == "sqlite":
        # SQLite: use sqlite insert with index_elements
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(CalendarEvent).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "google_event_id"],
            set_={k: stmt.excluded[k] for k in _update_set},
        )
    else:
        # PostgreSQL: use named constraint
        stmt = pg_insert(CalendarEvent).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_calendar_events_user_google",
            set_={k: stmt.excluded[k] for k in _update_set},
        )

    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount


async def list_events(
    db: AsyncSession,
    user_id: uuid.UUID,
    start_at: datetime,
    end_at: datetime,
    layer: str | None = None,
) -> list[CalendarEvent]:
    q = select(CalendarEvent).where(
        CalendarEvent.user_id == user_id,
        CalendarEvent.start_at >= start_at,
        CalendarEvent.start_at <= end_at,
    )
    if layer:
        q = q.where(CalendarEvent.layer == layer)
    q = q.order_by(CalendarEvent.start_at)
    result = await db.execute(q)
    return list(result.scalars().all())


async def delete_events_for_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(delete(CalendarEvent).where(CalendarEvent.user_id == user_id))
