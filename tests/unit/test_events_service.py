"""
Unit tests for app.modules.events.service — sync wrappers with asyncio.run().
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import AppException
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.events import service
from app.modules.events.schemas import EventCreate, EventUpdate
from tests.unit._db import make_session


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


async def _setup():
    factory, engine = await make_session()
    user_id = uuid.uuid4()
    async with factory() as db:
        db.add(User(id=user_id, email="ev@unit.com", hashed_password=hash_password("p"), full_name="U"))
        await db.commit()
    return factory, user_id


def _create_data(
    title: str = "Meeting",
    offset_hours: int = 0,
    duration: int = 1,
    layer: str = "work",
) -> EventCreate:
    start = datetime(2026, 5, 10, 9 + offset_hours, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=duration)
    return EventCreate(title=title, start_at=start, end_at=end, layer=layer)


# ── create ────────────────────────────────────────────────────────────────────


def test_create_event_returns_event():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            ev = await service.create_event(db, uid, _create_data())
            await db.commit()
            return ev

    ev = _run(_go())
    assert ev.title == "Meeting"
    assert ev.layer == "work"


def test_create_event_end_before_start_raises_400():
    async def _go():
        f, uid = await _setup()
        now = datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc)
        data = EventCreate(title="Bad", start_at=now, end_at=now - timedelta(hours=1), layer="work")
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.create_event(db, uid, data)
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 400
    assert "end_at" in exc.detail


def test_create_event_equal_start_end_raises_400():
    async def _go():
        f, uid = await _setup()
        now = datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc)
        data = EventCreate(title="Instant", start_at=now, end_at=now, layer="work")
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.create_event(db, uid, data)
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 400


# ── get ───────────────────────────────────────────────────────────────────────


def test_get_event_returns_event():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            ev = await service.create_event(db, uid, _create_data())
            await db.commit()
        async with f() as db:
            fetched = await service.get_event(db, uid, ev.id)
            return fetched

    ev = _run(_go())
    assert ev.title == "Meeting"


def test_get_event_not_found_raises_404():
    async def _go():
        f, uid = await _setup()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.get_event(db, uid, uuid.uuid4())
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 404


# ── list ──────────────────────────────────────────────────────────────────────


def test_list_events_returns_all():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            await service.create_event(db, uid, _create_data("A", 0))
            await service.create_event(db, uid, _create_data("B", 2))
            await db.commit()
        async with f() as db:
            return await service.list_events(db, uid, None, None, None)

    events = _run(_go())
    assert len(events) == 2


def test_list_events_filter_by_layer():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            await service.create_event(db, uid, _create_data("Work", layer="work"))
            await service.create_event(db, uid, _create_data("Family", layer="family"))
            await db.commit()
        async with f() as db:
            return await service.list_events(db, uid, None, None, "family")

    events = _run(_go())
    assert len(events) == 1
    assert events[0].layer == "family"


# ── update ────────────────────────────────────────────────────────────────────


def test_update_event_changes_title():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            ev = await service.create_event(db, uid, _create_data())
            await db.commit()
        async with f() as db:
            updated = await service.update_event(db, uid, ev.id, EventUpdate(title="Renamed"))
            await db.commit()
            return updated

    ev = _run(_go())
    assert ev.title == "Renamed"


def test_update_event_not_found_raises_404():
    async def _go():
        f, uid = await _setup()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.update_event(db, uid, uuid.uuid4(), EventUpdate(title="X"))
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 404


def test_update_event_bad_dates_raises_400():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            ev = await service.create_event(db, uid, _create_data())
            await db.commit()
        now = datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc)
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.update_event(
                    db, uid, ev.id,
                    EventUpdate(start_at=now + timedelta(hours=2), end_at=now),
                )
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 400


# ── delete ────────────────────────────────────────────────────────────────────


def test_delete_event_soft_deletes():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            ev = await service.create_event(db, uid, _create_data())
            await db.commit()
        async with f() as db:
            await service.delete_event(db, uid, ev.id)
            await db.commit()
        async with f() as db:
            events = await service.list_events(db, uid, None, None, None)
            return events

    events = _run(_go())
    assert len(events) == 0


def test_delete_event_not_found_raises_404():
    async def _go():
        f, uid = await _setup()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.delete_event(db, uid, uuid.uuid4())
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 404


# ── restore ───────────────────────────────────────────────────────────────────


def test_restore_event_makes_it_visible():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            ev = await service.create_event(db, uid, _create_data())
            await db.commit()
        async with f() as db:
            await service.delete_event(db, uid, ev.id)
            await db.commit()
        async with f() as db:
            restored = await service.restore_event(db, uid, ev.id)
            await db.commit()
            return restored

    ev = _run(_go())
    assert ev.title == "Meeting"


def test_restore_event_not_found_raises_404():
    async def _go():
        f, uid = await _setup()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.restore_event(db, uid, uuid.uuid4())
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 404
