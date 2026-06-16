"""
Unit tests for app.modules.calendar.service — mocked Google API calls.
All tests are synchronous (asyncio.run) for correct coverage tracking on Python 3.13.
"""
import asyncio
import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.core.exceptions import AppException
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.calendar import repository as repo
from app.modules.calendar import service
from tests.unit._db import make_session


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


_FERNET_KEY = Fernet.generate_key().decode()


async def _setup():
    factory, _ = await make_session()
    uid = uuid.uuid4()
    async with factory() as db:
        db.add(User(id=uid, email="cal@unit.com", hashed_password=hash_password("p"), full_name="U"))
        await db.commit()
    return factory, uid


# ── _get_fernet ───────────────────────────────────────────────────────────────


def test_get_fernet_raises_503_when_no_key():
    with patch.object(service.settings, "fernet_key", ""):
        with pytest.raises(AppException) as exc:
            service._get_fernet()
    assert exc.value.status_code == 503


def test_get_fernet_returns_fernet_when_key_set():
    with patch.object(service.settings, "fernet_key", _FERNET_KEY):
        f = service._get_fernet()
    assert f is not None


# ── build_oauth_url ───────────────────────────────────────────────────────────


def test_build_oauth_url_raises_503_when_not_configured():
    with patch.object(service.settings, "google_client_id", ""), \
         patch.object(service.settings, "google_client_secret", ""):
        with pytest.raises(AppException) as exc:
            service.build_oauth_url("state123", "http://localhost/cb")
    assert exc.value.status_code == 503


def test_build_oauth_url_contains_state():
    with patch.object(service.settings, "google_client_id", "test-id"), \
         patch.object(service.settings, "google_client_secret", "test-secret"):
        url = service.build_oauth_url("my_state", "http://localhost/cb")
    assert "state=my_state" in url
    assert "accounts.google.com" in url


def test_build_oauth_url_contains_required_scopes():
    with patch.object(service.settings, "google_client_id", "test-id"), \
         patch.object(service.settings, "google_client_secret", "test-secret"):
        url = service.build_oauth_url("s", "http://localhost/cb")
    assert "calendar.readonly" in url


# ── decode_id_token ───────────────────────────────────────────────────────────


def _make_id_token(sub: str, email: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub, "email": email}).encode()).decode()
    return f"header.{payload}.sig"


def test_decode_id_token_returns_sub_and_email():
    token = _make_id_token("google-123", "test@gmail.com")
    sub, email = service.decode_id_token(token)
    assert sub == "google-123"
    assert email == "test@gmail.com"


def test_decode_id_token_bad_format_raises_400():
    with pytest.raises(AppException) as exc:
        service.decode_id_token("notavalidtoken")
    assert exc.value.status_code == 400


# ── encrypt / decrypt ─────────────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip():
    f = Fernet(_FERNET_KEY.encode())
    encrypted = service._encrypt(f, "my_secret_token")
    decrypted = service._decrypt(f, encrypted)
    assert decrypted == "my_secret_token"


# ── get_status ────────────────────────────────────────────────────────────────


def test_get_status_returns_not_connected():
    async def _go():
        f, uid = await _setup()
        async with f() as db:
            return await service.get_status(db, uid)

    status = _run(_go())
    assert status.connected is False
    assert status.google_email is None


def test_get_status_returns_connected_after_account_saved():
    async def _go():
        f, uid = await _setup()
        fernet = Fernet(_FERNET_KEY.encode())
        async with f() as db:
            await repo.save_google_account(
                db,
                user_id=uid,
                google_account_id="g-123",
                google_email="u@gmail.com",
                access_token_enc=service._encrypt(fernet, "access"),
                refresh_token_enc=service._encrypt(fernet, "refresh"),
                token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
                scopes="calendar",
            )
            await db.commit()
        async with f() as db:
            return await service.get_status(db, uid)

    status = _run(_go())
    assert status.connected is True
    assert status.google_email == "u@gmail.com"


# ── disconnect_calendar ───────────────────────────────────────────────────────


def test_disconnect_calendar_removes_account():
    async def _go():
        f, uid = await _setup()
        fernet = Fernet(_FERNET_KEY.encode())
        async with f() as db:
            await repo.save_google_account(
                db, uid, "g-123", "u@gmail.com",
                service._encrypt(fernet, "at"), service._encrypt(fernet, "rt"),
                None, "",
            )
            await db.commit()
        async with f() as db:
            await service.disconnect_calendar(db, uid)
            await db.commit()
        async with f() as db:
            return await service.get_status(db, uid)

    status = _run(_go())
    assert status.connected is False


# ── sync_user_calendar ────────────────────────────────────────────────────────


def test_sync_without_account_raises_400():
    async def _go():
        f, uid = await _setup()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.sync_user_calendar(db, uid)
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 400
    assert "not connected" in exc.detail.lower()


def test_sync_with_mocked_google_api():
    """Full sync flow with mocked httpx responses."""
    google_items = [
        {
            "id": "evt-1",
            "summary": "Team Meeting",
            "status": "confirmed",
            "start": {"dateTime": "2026-05-10T09:00:00+00:00"},
            "end": {"dateTime": "2026-05-10T10:00:00+00:00"},
        },
        {
            "id": "evt-cancelled",
            "status": "cancelled",
            "start": {"dateTime": "2026-05-10T11:00:00+00:00"},
            "end": {"dateTime": "2026-05-10T12:00:00+00:00"},
        },
        {
            "id": "evt-allday",
            "summary": "Holiday",
            "status": "confirmed",
            "start": {"date": "2026-05-20"},
            "end": {"date": "2026-05-21"},
        },
    ]

    async def _go():
        f, uid = await _setup()
        fernet = Fernet(_FERNET_KEY.encode())
        async with f() as db:
            await repo.save_google_account(
                db, uid, "g-123", "u@gmail.com",
                service._encrypt(fernet, "access_token"),
                service._encrypt(fernet, "refresh_token"),
                datetime.now(timezone.utc) + timedelta(hours=1),
                "calendar",
            )
            await db.commit()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"items": google_items}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(service.settings, "fernet_key", _FERNET_KEY), \
             patch("app.modules.calendar.service.httpx.AsyncClient", return_value=mock_client):
            async with f() as db:
                count = await service.sync_user_calendar(db, uid)
                await db.commit()
        return count

    count = _run(_go())
    assert count == 2  # cancelled event excluded


def test_sync_handles_google_api_error():
    async def _go():
        f, uid = await _setup()
        fernet = Fernet(_FERNET_KEY.encode())
        async with f() as db:
            await repo.save_google_account(
                db, uid, "g-123", "u@gmail.com",
                service._encrypt(fernet, "at"), service._encrypt(fernet, "rt"),
                datetime.now(timezone.utc) + timedelta(hours=1), "",
            )
            await db.commit()

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(service.settings, "fernet_key", _FERNET_KEY), \
             patch("app.modules.calendar.service.httpx.AsyncClient", return_value=mock_client), \
             pytest.raises(AppException) as exc:
            async with f() as db:
                await service.sync_user_calendar(db, uid)
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 502


def test_sync_triggers_token_refresh_when_expired():
    """When access token is expired, _refresh_access_token is called."""
    async def _go():
        f, uid = await _setup()
        fernet = Fernet(_FERNET_KEY.encode())
        async with f() as db:
            await repo.save_google_account(
                db, uid, "g-123", "u@gmail.com",
                service._encrypt(fernet, "old_access"),
                service._encrypt(fernet, "refresh_tok"),
                datetime.now(timezone.utc) - timedelta(hours=1),  # expired
                "",
            )
            await db.commit()

        refresh_response = MagicMock()
        refresh_response.status_code = 200
        refresh_response.json.return_value = {
            "access_token": "new_access_token",
            "expires_in": 3600,
        }

        events_response = MagicMock()
        events_response.status_code = 200
        events_response.json.return_value = {"items": []}

        call_count = {"n": 0}

        async def _post(*a, **kw):
            call_count["n"] += 1
            return refresh_response

        async def _get(*a, **kw):
            return events_response

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=_post)
        mock_client.get = AsyncMock(side_effect=_get)

        with patch.object(service.settings, "fernet_key", _FERNET_KEY), \
             patch.object(service.settings, "google_client_id", "id"), \
             patch.object(service.settings, "google_client_secret", "secret"), \
             patch("app.modules.calendar.service.httpx.AsyncClient", return_value=mock_client):
            async with f() as db:
                count = await service.sync_user_calendar(db, uid)
                await db.commit()
        return count, call_count["n"]

    count, refresh_calls = _run(_go())
    assert count == 0  # no items
    assert refresh_calls == 1  # token was refreshed


# ── exchange_code ─────────────────────────────────────────────────────────────


def test_exchange_code_raises_400_on_google_error():
    async def _go():
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "bad_request"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(service.settings, "google_client_id", "id"), \
             patch.object(service.settings, "google_client_secret", "secret"), \
             patch("app.modules.calendar.service.httpx.AsyncClient", return_value=mock_client), \
             pytest.raises(AppException) as exc:
            await service.exchange_code("bad_code", "http://cb")
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 400
