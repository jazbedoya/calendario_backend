import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event
from .schemas import BusyDay, LayerStat, MonthlyStats


async def get_monthly_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
    year: int,
    month: int,
) -> MonthlyStats:
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc)

    result = await db.execute(
        select(Event).where(
            Event.user_id == user_id,
            Event.deleted_at.is_(None),
            Event.start_at >= start,
            Event.start_at < end,
        )
    )
    events = result.scalars().all()

    # ── By layer ──────────────────────────────────────────────────────────────
    layer_data: dict[str, dict] = {}
    day_counts: dict[str, int] = {}

    for e in events:
        if e.layer not in layer_data:
            layer_data[e.layer] = {"count": 0, "seconds": 0}
        layer_data[e.layer]["count"] += 1
        layer_data[e.layer]["seconds"] += max(0, (e.end_at - e.start_at).total_seconds())

        day_key = e.start_at.strftime("%Y-%m-%d")
        day_counts[day_key] = day_counts.get(day_key, 0) + 1

    by_layer = [
        LayerStat(
            layer=layer,
            count=v["count"],
            total_hours=round(v["seconds"] / 3600, 1),
        )
        for layer, v in layer_data.items()
    ]

    busiest_days = sorted(
        [BusyDay(date=d, count=c) for d, c in day_counts.items()],
        key=lambda x: x.count,
        reverse=True,
    )[:5]

    return MonthlyStats(
        year=year,
        month=month,
        total_events=len(events),
        by_layer=by_layer,
        busiest_days=busiest_days,
    )
