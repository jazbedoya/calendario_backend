"""
Unit tests for: dependencies.py, core/exceptions.py, workers/calendar_sync.py.
All sync wrappers using asyncio.run() for correct Python 3.13 coverage tracking.
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials

from app.core.exceptions import AppException, app_exception_handler, unhandled_exception_handler
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import User
from tests.unit._db import make_session


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


# ── AppException handler ──────────────────────────────────────────────────────


def test_app_exception_handler_returns_json():
    async def _go():
        request = MagicMock(spec=Request)
        exc = AppException(404, "Not found")
        return await app_exception_handler(request, exc)

    response = _run(_go())
    assert response.status_code == 404


def test_app_exception_handler_detail_in_body():
    async def _go():
        request = MagicMock(spec=Request)
        exc = AppException(400, "Bad input")
        return await app_exception_handler(request, exc)

    response = _run(_go())
    import json as _json
    body = _json.loads(response.body)
    assert body["detail"] == "Bad input"


def test_unhandled_exception_handler_returns_500():
    async def _go():
        request = MagicMock(spec=Request)
        exc = RuntimeError("Something went wrong")
        return await unhandled_exception_handler(request, exc)

    response = _run(_go())
    assert response.status_code == 500


# ── get_current_user — error paths ────────────────────────────────────────────


def test_get_current_user_wrong_token_type_raises_401():
    """Token type != 'access' should raise 401."""
    async def _go():
        from jose import jwt
        from app.config import settings
        from app.core.security import ALGORITHM
        from app.dependencies import get_current_user

        # Manually create a token with type="refresh"
        payload = {"sub": str(uuid.uuid4()), "type": "refresh", "exp": 9999999999}
        token = jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        factory, _ = await make_session()
        async with factory() as db:
            with pytest.raises(AppException) as exc:
                await get_current_user(credentials, db)
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 401
    assert "token type" in exc.detail.lower()


def test_get_current_user_user_not_in_db_raises_401():
    """Valid JWT but user doesn't exist in DB → 401."""
    async def _go():
        from app.dependencies import get_current_user

        token = create_access_token(str(uuid.uuid4()))
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        factory, _ = await make_session()
        async with factory() as db:
            with pytest.raises(AppException) as exc:
                await get_current_user(credentials, db)
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 401
    assert "not found" in exc.detail.lower()


def test_get_current_user_invalid_jwt_raises_401():
    async def _go():
        from app.dependencies import get_current_user

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not.a.token")
        factory, _ = await make_session()
        async with factory() as db:
            with pytest.raises(AppException) as exc:
                await get_current_user(credentials, db)
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 401


def test_get_current_user_returns_user_for_valid_token():
    async def _go():
        from app.dependencies import get_current_user

        factory, _ = await make_session()
        uid = uuid.uuid4()
        async with factory() as db:
            db.add(User(id=uid, email="dep@unit.com", hashed_password=hash_password("p"), full_name="U"))
            await db.commit()

        token = create_access_token(str(uid))
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        async with factory() as db:
            user = await get_current_user(credentials, db)
        return user

    user = _run(_go())
    assert user.email == "dep@unit.com"


# ── ARQ worker — calendar_sync_task ──────────────────────────────────────────


def test_sync_calendar_task_success():
    async def _go():
        from app.workers.calendar_sync import sync_calendar_task

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        with patch("app.workers.calendar_sync.AsyncSessionLocal", return_value=mock_db), \
             patch("app.workers.calendar_sync.service.sync_user_calendar", new=AsyncMock(return_value=5)):
            ctx: dict = {}
            result = await sync_calendar_task(ctx, str(uuid.uuid4()))
        return result

    result = _run(_go())
    assert result["synced"] == 5


def test_sync_calendar_task_rollback_on_error():
    async def _go():
        from app.workers.calendar_sync import sync_calendar_task
        from app.core.exceptions import AppException

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        with patch("app.workers.calendar_sync.AsyncSessionLocal", return_value=mock_db), \
             patch(
                 "app.workers.calendar_sync.service.sync_user_calendar",
                 new=AsyncMock(side_effect=AppException(400, "not connected")),
             ), \
             pytest.raises(AppException):
            await sync_calendar_task({}, str(uuid.uuid4()))

        return mock_db.rollback.called

    rolled_back = _run(_go())
    assert rolled_back


def test_worker_settings_has_sync_function():
    from app.workers.calendar_sync import WorkerSettings, sync_calendar_task

    assert sync_calendar_task in WorkerSettings.functions
