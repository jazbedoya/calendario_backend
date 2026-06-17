import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event
from app.modules.tasks.models import DailyTask
from app.modules.home.schemas import HomeSummary, UpcomingEvent, WeekEventCount


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

    # ── 2. Conteo de eventos por área esta semana ─────────────────────────────
    week_start, week_end = _week_bounds()
    result2 = await db.execute(
        select(Event.layer, func.count(Event.id))
        .where(
            Event.user_id == user_id,
            Event.deleted_at.is_(None),
            Event.start_at >= week_start,
            Event.start_at <= week_end,
            Event.layer.in_(["family", "work", "personal"]),
        )
        .group_by(Event.layer)
    )
    counts: dict[str, int] = {"family": 0, "work": 0, "personal": 0}
    for layer, count in result2.all():
        if layer in counts:
            counts[layer] = count

    week_events = WeekEventCount(
        family=counts["family"],
        work=counts["work"],
        personal=counts["personal"],
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
        week_events_by_layer=week_events,
        today_tasks_pending=today_tasks_pending,
    )
