"""
Unit tests for app.modules.auth.service — sync wrappers with asyncio.run()
so that coverage.py / sys.settrace tracks async coroutine bodies correctly on Python 3.13.
"""
import asyncio
import uuid
from datetime import date

import pytest

from app.core.exceptions import AppException
from app.modules.auth import repository as repo
from app.modules.auth.schemas import LoginRequest, PatchMeRequest, SignupRequest
from app.modules.auth import service
from tests.unit._db import make_session

# ── helpers ───────────────────────────────────────────────────────────────────

_SIGNUP = SignupRequest(
    email="unit@example.com",
    password="UnitPass123",
    full_name="Unit User",
    timezone="UTC",
)

_BASE_URL = "http://test"


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


async def _db():
    factory, _ = await make_session()
    return factory


async def _signup_and_verify(f, data: SignupRequest = _SIGNUP) -> None:
    """Sign up a user and mark their email as verified (bypasses email sending)."""
    async with f() as db:
        await service.signup(db, data, _BASE_URL)
        await db.commit()
    async with f() as db:
        user = await repo.get_user_by_email(db, data.email)
        assert user is not None
        await repo.mark_email_verified(db, user)
        await db.commit()


async def _login(f, data: SignupRequest = _SIGNUP):
    async with f() as db:
        r = await service.login(db, LoginRequest(email=data.email, password=data.password))
        await db.commit()
        return r


# ── signup ────────────────────────────────────────────────────────────────────


def test_signup_returns_pending_verification():
    async def _go():
        f = await _db()
        async with f() as db:
            r = await service.signup(db, _SIGNUP, _BASE_URL)
            await db.commit()
            return r

    r = _run(_go())
    assert r.email == _SIGNUP.email


def test_signup_duplicate_email_raises_400():
    async def _go():
        f = await _db()
        await _signup_and_verify(f)
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.signup(db, _SIGNUP, _BASE_URL)
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 400
    assert "already registered" in exc.detail


# ── login ─────────────────────────────────────────────────────────────────────


def test_login_returns_tokens():
    async def _go():
        f = await _db()
        await _signup_and_verify(f)
        return await _login(f)

    r = _run(_go())
    assert r.access_token
    assert r.refresh_token


def test_login_before_verification_raises_403():
    async def _go():
        f = await _db()
        async with f() as db:
            await service.signup(db, _SIGNUP, _BASE_URL)
            await db.commit()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.login(db, LoginRequest(email=_SIGNUP.email, password=_SIGNUP.password))
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 403
    assert "email_not_verified" in exc.detail


def test_login_wrong_password_raises_401():
    async def _go():
        f = await _db()
        await _signup_and_verify(f)
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.login(db, LoginRequest(email=_SIGNUP.email, password="wrongpass"))
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 401


def test_login_unknown_email_raises_401():
    async def _go():
        f = await _db()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.login(db, LoginRequest(email="nobody@x.com", password="x"))
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 401


# ── refresh ───────────────────────────────────────────────────────────────────


def test_refresh_returns_new_tokens():
    async def _go():
        f = await _db()
        await _signup_and_verify(f)
        tokens = await _login(f)
        async with f() as db:
            new_tokens = await service.refresh(db, tokens.refresh_token)
            await db.commit()
            return tokens, new_tokens

    old, new = _run(_go())
    assert new.access_token
    assert new.refresh_token != old.refresh_token


def test_refresh_invalid_token_raises_401():
    async def _go():
        f = await _db()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.refresh(db, "fake-token")
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 401


def test_refresh_reused_token_raises_401():
    async def _go():
        f = await _db()
        await _signup_and_verify(f)
        tokens = await _login(f)
        async with f() as db:
            await service.refresh(db, tokens.refresh_token)
            await db.commit()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.refresh(db, tokens.refresh_token)
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 401


# ── logout ────────────────────────────────────────────────────────────────────


def test_logout_revokes_refresh_token():
    async def _go():
        f = await _db()
        await _signup_and_verify(f)
        tokens = await _login(f)
        from app.core.security import decode_access_token
        payload = decode_access_token(tokens.access_token)
        user_id = uuid.UUID(payload["sub"])
        async with f() as db:
            await service.logout(db, user_id)
            await db.commit()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.refresh(db, tokens.refresh_token)
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 401


# ── get_user_by_id ────────────────────────────────────────────────────────────


def test_get_user_by_id_returns_user():
    async def _go():
        f = await _db()
        await _signup_and_verify(f)
        tokens = await _login(f)
        from app.core.security import decode_access_token
        user_id_str = decode_access_token(tokens.access_token)["sub"]
        async with f() as db:
            user = await service.get_user_by_id(db, user_id_str)
            return user

    user = _run(_go())
    assert user.email == _SIGNUP.email


def test_get_user_by_id_not_found_raises_401():
    async def _go():
        f = await _db()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.get_user_by_id(db, str(uuid.uuid4()))
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 401


def test_get_user_by_id_invalid_uuid_raises_401():
    async def _go():
        f = await _db()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.get_user_by_id(db, "not-a-uuid")
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 401


# ── update_me / weekly_intentions ─────────────────────────────────────────────


def test_update_me_weekly_intentions_persists():
    async def _go():
        f = await _db()
        await _signup_and_verify(f)
        tokens = await _login(f)
        from app.core.security import decode_access_token
        user_id_str = decode_access_token(tokens.access_token)["sub"]
        async with f() as db:
            user = await service.get_user_by_id(db, user_id_str)
            data = PatchMeRequest(
                weekly_intentions=["family_time", "reconnect"],
                weekly_intentions_week=date(2026, 5, 26),
            )
            updated = await service.update_me(db, user, data)
            await db.commit()
            return updated

    updated = _run(_go())
    assert updated.weekly_intentions == ["family_time", "reconnect"]
    assert updated.weekly_intentions_week == date(2026, 5, 26)


def test_update_me_weekly_intentions_none_leaves_unchanged():
    async def _go():
        f = await _db()
        await _signup_and_verify(f)
        tokens = await _login(f)
        from app.core.security import decode_access_token
        user_id_str = decode_access_token(tokens.access_token)["sub"]
        async with f() as db:
            user = await service.get_user_by_id(db, user_id_str)
            await service.update_me(db, user, PatchMeRequest(
                weekly_intentions=["personal_space"],
                weekly_intentions_week=date(2026, 5, 26),
            ))
            await db.commit()
        async with f() as db:
            user = await service.get_user_by_id(db, user_id_str)
            updated = await service.update_me(db, user, PatchMeRequest(mascot_name="Shelby"))
            await db.commit()
            return updated

    updated = _run(_go())
    assert updated.weekly_intentions == ["personal_space"]
    assert updated.mascot_name == "Shelby"


# ── verify_email ──────────────────────────────────────────────────────────────


def test_verify_email_marks_user_verified():
    from tests.conftest import _captured_tokens

    async def _go():
        f = await _db()
        async with f() as db:
            await service.signup(db, _SIGNUP, _BASE_URL)
            await db.commit()

        token = _captured_tokens.get(_SIGNUP.email)
        assert token, "Verification token was not captured"

        async with f() as db:
            await service.verify_email(db, token)
            await db.commit()

        async with f() as db:
            user = await repo.get_user_by_email(db, _SIGNUP.email)
            return user

    user = _run(_go())
    assert user.email_verified is True
    assert user.email_verification_token is None


def test_verify_email_invalid_token_raises_400():
    async def _go():
        f = await _db()
        with pytest.raises(AppException) as exc:
            async with f() as db:
                await service.verify_email(db, "badtoken")
        return exc.value

    exc = _run(_go())
    assert exc.status_code == 400
