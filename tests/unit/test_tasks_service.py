"""
Unit tests for app.modules.tasks.service — sync wrappers with asyncio.run().
"""
import asyncio
import uuid
from datetime import date

import pytest

from app.core.exceptions import AppException
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.tasks import service
from app.modules.tasks.schemas import CreateTaskRequest, PatchTaskRequest
from tests.unit._db import make_session

TODAY = date(2026, 5, 28)
OTHER_DAY = date(2026, 5, 27)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


async def _setup(email: str = "tasks@unit.com") -> tuple:
    factory, _ = await make_session()
    user_id = uuid.uuid4()
    async with factory() as db:
        db.add(User(id=user_id, email=email, hashed_password=hash_password("p"), full_name="U"))
        await db.commit()
    return factory, user_id


def _req(text: str = "Hacer ejercicio", day: date = TODAY) -> CreateTaskRequest:
    return CreateTaskRequest(date=day, text=text)


# ── create ────────────────────────────────────────────────────────────────────


def test_create_task_returns_task():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            t = await service.create(db, uid, _req())
            await db.commit()
            return t

    t = _run(_go())
    assert t.text == "Hacer ejercicio"
    assert t.done is False
    assert t.date == TODAY
    assert t.order == 0


def test_create_task_increments_order():
    async def _go():
        f, uid = await _setup("order@unit.com")
        async with f() as db:
            t1 = await service.create(db, uid, _req("T1"))
            t2 = await service.create(db, uid, _req("T2"))
            await db.commit()
            return t1, t2

    t1, t2 = _run(_go())
    assert t1.order == 0
    assert t2.order == 1


# ── list ──────────────────────────────────────────────────────────────────────


def test_list_today_returns_only_that_date():
    async def _go():
        f, uid = await _setup("list@unit.com")
        async with f() as db:
            await service.create(db, uid, _req("Hoy", TODAY))
            await service.create(db, uid, _req("Ayer", OTHER_DAY))
            await db.commit()
        async with f() as db:
            return await service.list_today(db, uid, TODAY)

    tasks = _run(_go())
    assert len(tasks) == 1
    assert tasks[0].date == TODAY


def test_list_only_own_tasks():
    async def _go():
        f, uid_a = await _setup("own_a@unit.com")
        uid_b = uuid.uuid4()
        async with f() as db:
            db.add(User(id=uid_b, email="own_b@unit.com", hashed_password=hash_password("p"), full_name="B"))
            await db.commit()
        async with f() as db:
            await service.create(db, uid_a, _req("Task de A"))
            await db.commit()
        async with f() as db:
            return await service.list_today(db, uid_b, TODAY)

    tasks = _run(_go())
    assert tasks == []


# ── patch ─────────────────────────────────────────────────────────────────────


def test_patch_task_done():
    async def _go():
        f, uid = await _setup("done@unit.com")
        async with f() as db:
            t = await service.create(db, uid, _req())
            await db.commit()
        async with f() as db:
            updated = await service.patch(db, uid, t.id, PatchTaskRequest(done=True))
            await db.commit()
            return updated

    t = _run(_go())
    assert t.done is True


def test_patch_task_text():
    async def _go():
        f, uid = await _setup("text@unit.com")
        async with f() as db:
            t = await service.create(db, uid, _req())
            await db.commit()
        async with f() as db:
            updated = await service.patch(db, uid, t.id, PatchTaskRequest(text="  Nuevo texto  "))
            await db.commit()
            return updated

    t = _run(_go())
    assert t.text == "Nuevo texto"  # strips whitespace


def test_patch_task_not_found_raises_404():
    async def _go():
        f, uid = await _setup("notfound@unit.com")
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.patch(db, uid, uuid.uuid4(), PatchTaskRequest(done=True))
        return exc.value.status_code

    assert _run(_go()) == 404


# ── delete ────────────────────────────────────────────────────────────────────


def test_delete_task_removes_it():
    async def _go():
        f, uid = await _setup("del@unit.com")
        async with f() as db:
            t = await service.create(db, uid, _req())
            await db.commit()
        async with f() as db:
            await service.delete(db, uid, t.id)
            await db.commit()
        async with f() as db:
            return await service.list_today(db, uid, TODAY)

    tasks = _run(_go())
    assert tasks == []


def test_delete_task_not_found_raises_404():
    async def _go():
        f, uid = await _setup("delnf@unit.com")
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.delete(db, uid, uuid.uuid4())
        return exc.value.status_code

    assert _run(_go()) == 404
