import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
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


async def upsert_event(
    db: AsyncSession,
    user_id: uuid.UUID,
    google_event_id: str,
    calendar_id: str,
    title: str,
    description: str | None,
    start_at: datetime,
    end_at: datetime,
    is_all_day: bool,
    location: str | None,
) -> CalendarEvent:
    result = await db.execute(
        select(CalendarEvent).where(
            CalendarEvent.user_id == user_id,
            CalendarEvent.google_event_id == google_event_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        await db.execute(
            update(CalendarEvent)
            .where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.google_event_id == google_event_id,
            )
            .values(
                calendar_id=calendar_id,
                title=title,
                description=description,
                start_at=start_at,
                end_at=end_at,
                is_all_day=is_all_day,
                location=location,
            )
        )
        await db.flush()
        return existing

    event = CalendarEvent(
        user_id=user_id,
        google_event_id=google_event_id,
        calendar_id=calendar_id,
        title=title,
        description=description,
        start_at=start_at,
        end_at=end_at,
        is_all_day=is_all_day,
        location=location,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return event


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
