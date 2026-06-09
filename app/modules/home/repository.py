import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event
from app.modules.tasks.models import DailyTask
from app.modules.home.schemas import HomeSummary, UpcomingEvent, WeekHours


def _week_bounds() -> tuple[datetime, datetime]:
    """Return (monday 00:00 UTC, sunday 23:59:59 UTC) of the current week."""
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())  # weekday() 0=Mon
    sunday = monday + timedelta(days=6)
    start = datetime(monday.year, monday.month, monday.day, 0, 0, 0, tzinfo=timezone.utc)
    end   = datetime(sunday.year, sunday.month, sunday.day, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


async def get_home_summary(db: AsyncSession, user_id: uuid.UUID) -> HomeSummary:
    now = datetime.now(timezone.utc)

    # ── 1. Próximos 5 eventos ─────────────────────────────────────────────────
    result = await db.execute(
        select(Event)
        .where(
            Event.user_id == user_id,
            Event.start_at >= now,
            Event.deleted_at.is_(None),
        )
        .order_by(Event.start_at.asc())
        .limit(5)
    )
    upcoming_rows = list(result.scalars().all())

    upcoming_events = [
        UpcomingEvent(
            id=str(e.id),
            title=e.title,
            start_at=e.start_at.isoformat(),
            end_at=e.end_at.isoformat(),
            layer=e.layer,
            is_all_day=e.is_all_day,
        )
        for e in upcoming_rows
    ]

    # ── 2. Horas por área esta semana ─────────────────────────────────────────
    week_start, week_end = _week_bounds()
    result2 = await db.execute(
        select(Event.layer, Event.start_at, Event.end_at)
        .where(
            Event.user_id == user_id,
            Event.deleted_at.is_(None),
            Event.start_at >= week_start,
            Event.start_at <= week_end,
            Event.layer.in_(["family", "work", "personal"]),
        )
    )
    rows = result2.all()

    hours: dict[str, float] = {"family": 0.0, "work": 0.0, "personal": 0.0}
    for layer, start_at, end_at in rows:
        diff = (end_at - start_at).total_seconds() / 3600
        if layer in hours:
            hours[layer] += diff

    week_hours = WeekHours(
        family=round(hours["family"], 1),
        work=round(hours["work"], 1),
        personal=round(hours["personal"], 1),
    )

    # ── 3. Tareas pendientes hoy ──────────────────────────────────────────────
    today = date.today()
    result3 = await db.execute(
        select(func.count(DailyTask.id)).where(
            DailyTask.user_id == user_id,
            DailyTask.date == today,
            DailyTask.done.is_(False),
        )
    )
    today_tasks_pending = result3.scalar_one() or 0

    return HomeSummary(
        upcoming_events=upcoming_events,
        week_hours_by_layer=week_hours,
        today_tasks_pending=today_tasks_pending,
    )
