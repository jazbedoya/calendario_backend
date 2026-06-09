"""
Unit tests for app.modules.context.service — sync wrappers with asyncio.run().
"""
import asyncio
import uuid
from datetime import date

import pytest

from app.core.exceptions import AppException
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.context import service
from app.modules.context.schemas import ContextEntryCreate, ContextEntryUpdate
from tests.unit._db import make_session


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


async def _setup():
    factory, _ = await make_session()
    user_id = uuid.uuid4()
    async with factory() as db:
        db.add(User(id=user_id, email="ctx@unit.com", hashed_password=hash_password("p"), full_name="U"))
        await db.commit()
    return factory, user_id


def _entry(d: str = "2026-05-10", energy: int = 7, mood: int = 8) -> ContextEntryCreate:
    return ContextEntryCreate(date=date.fromisoformat(d), energy_level=energy, mood=mood)


# ── create ────────────────────────────────────────────────────────────────────


def test_create_entry_returns_entry():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            e = await service.create_entry(db, uid, _entry())
            await db.commit()
            return e

    e = _run(_go())
    assert e.energy_level == 7
    assert e.mood == 8


# ── list ──────────────────────────────────────────────────────────────────────


def test_list_entries_returns_all():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            await service.create_entry(db, uid, _entry("2026-05-01"))
            await service.create_entry(db, uid, _entry("2026-05-15"))
            await db.commit()
        async with f() as db:
            return await service.list_entries(db, uid, None, None)

    entries = _run(_go())
    assert len(entries) == 2


def test_list_entries_filter_by_date():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            await service.create_entry(db, uid, _entry("2026-04-01"))
            await service.create_entry(db, uid, _entry("2026-05-15"))
            await service.create_entry(db, uid, _entry("2026-06-01"))
            await db.commit()
        async with f() as db:
            return await service.list_entries(
                db, uid,
                date.fromisoformat("2026-05-01"),
                date.fromisoformat("2026-05-31"),
            )

    entries = _run(_go())
    assert len(entries) == 1
    assert str(entries[0].date) == "2026-05-15"


# ── get ───────────────────────────────────────────────────────────────────────


def test_get_entry_returns_entry():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            e = await service.create_entry(db, uid, _entry())
            await db.commit()
        async with f() as db:
            return await service.get_entry(db, uid, e.id)

    e = _run(_go())
    assert e.energy_level == 7


def test_get_entry_not_found_raises_404():
    async def _go():
        f, uid = await _setup()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.get_entry(db, uid, uuid.uuid4())
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 404
    assert "not found" in exc.detail.lower()


# ── update ────────────────────────────────────────────────────────────────────


def test_update_entry_changes_energy():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            e = await service.create_entry(db, uid, _entry())
            await db.commit()
        async with f() as db:
            updated = await service.update_entry(db, uid, e.id, ContextEntryUpdate(energy_level=3))
            await db.commit()
            return updated

    e = _run(_go())
    assert e.energy_level == 3


def test_update_entry_not_found_raises_404():
    async def _go():
        f, uid = await _setup()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.update_entry(db, uid, uuid.uuid4(), ContextEntryUpdate(energy_level=5))
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 404


# ── delete ────────────────────────────────────────────────────────────────────


def test_delete_entry_removes_it():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            e = await service.create_entry(db, uid, _entry())
            await db.commit()
        async with f() as db:
            await service.delete_entry(db, uid, e.id)
            await db.commit()
        async with f() as db:
            return await service.list_entries(db, uid, None, None)

    entries = _run(_go())
    assert len(entries) == 0


def test_delete_entry_not_found_raises_404():
    async def _go():
        f, uid = await _setup()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.delete_entry(db, uid, uuid.uuid4())
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 404
