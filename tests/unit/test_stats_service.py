"""
Unit tests for app.modules.stats.service — sync wrappers with asyncio.run().
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.events import service as event_svc
from app.modules.events.schemas import EventCreate
from app.modules.stats import service as stats_svc
from tests.unit._db import make_session


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


async def _setup():
    factory, _ = await make_session()
    uid = uuid.uuid4()
    async with factory() as db:
        db.add(User(id=uid, email="stats@unit.com", hashed_password=hash_password("p"), full_name="U"))
        await db.commit()
    return factory, uid


def _ev(title: str, day: int, hours: int = 1, layer: str = "work") -> EventCreate:
    start = datetime(2026, 5, day, 9, 0, tzinfo=timezone.utc)
    return EventCreate(title=title, start_at=start, end_at=start + timedelta(hours=hours), layer=layer)


# ── empty month ───────────────────────────────────────────────────────────────


def test_stats_empty_month():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            return await stats_svc.get_monthly_stats(db, uid, 2026, 5)

    s = _run(_go())
    assert s.total_events == 0
    assert s.by_layer == []
    assert s.busiest_days == []


# ── event counting ────────────────────────────────────────────────────────────


def test_stats_counts_events_by_layer():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            await event_svc.create_event(db, uid, _ev("W1", 1))
            await event_svc.create_event(db, uid, _ev("W2", 2))
            await event_svc.create_event(db, uid, _ev("F", 3, layer="family"))
            await db.commit()
        async with f() as db:
            return await stats_svc.get_monthly_stats(db, uid, 2026, 5)

    s = _run(_go())
    assert s.total_events == 3
    layers = {l.layer: l for l in s.by_layer}
    assert layers["work"].count == 2
    assert layers["family"].count == 1


def test_stats_hours_calculation():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            await event_svc.create_event(db, uid, _ev("Long", 1, hours=3))
            await db.commit()
        async with f() as db:
            return await stats_svc.get_monthly_stats(db, uid, 2026, 5)

    s = _run(_go())
    assert s.by_layer[0].total_hours == 3.0


def test_stats_excludes_deleted_events():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            ev = await event_svc.create_event(db, uid, _ev("ToDelete", 1))
            await db.commit()
        async with f() as db:
            await event_svc.delete_event(db, uid, ev.id)
            await db.commit()
        async with f() as db:
            return await stats_svc.get_monthly_stats(db, uid, 2026, 5)

    s = _run(_go())
    assert s.total_events == 0


def test_stats_busiest_days_ordered_desc():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            for i in range(3):
                start = datetime(2026, 5, 10, 9 + i, 0, tzinfo=timezone.utc)
                await event_svc.create_event(
                    db, uid,
                    EventCreate(title=f"E{i}", start_at=start, end_at=start + timedelta(hours=1), layer="work"),
                )
            start = datetime(2026, 5, 15, 9, 0, tzinfo=timezone.utc)
            await event_svc.create_event(
                db, uid,
                EventCreate(title="Solo", start_at=start, end_at=start + timedelta(hours=1), layer="work"),
            )
            await db.commit()
        async with f() as db:
            return await stats_svc.get_monthly_stats(db, uid, 2026, 5)

    s = _run(_go())
    assert s.busiest_days[0].date == "2026-05-10"
    assert s.busiest_days[0].count == 3


def test_stats_december_boundary():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            dec = datetime(2026, 12, 15, 9, 0, tzinfo=timezone.utc)
            jan = datetime(2027, 1, 5, 9, 0, tzinfo=timezone.utc)
            await event_svc.create_event(db, uid, EventCreate(title="Dec", start_at=dec, end_at=dec + timedelta(hours=1), layer="work"))
            await event_svc.create_event(db, uid, EventCreate(title="Jan", start_at=jan, end_at=jan + timedelta(hours=1), layer="work"))
            await db.commit()
        async with f() as db:
            s_dec = await stats_svc.get_monthly_stats(db, uid, 2026, 12)
            s_jan = await stats_svc.get_monthly_stats(db, uid, 2027, 1)
            return s_dec, s_jan

    s_dec, s_jan = _run(_go())
    assert s_dec.total_events == 1
    assert s_jan.total_events == 1
