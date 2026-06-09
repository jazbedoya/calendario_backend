"""
Integration tests: Google Calendar OAuth state encoding, endpoint auth guards,
calendar status, sync without connection, calendar events listing.
"""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

SIGNUP_URL = "/auth/signup"
CALENDAR_CONNECT_URL = "/calendar/connect"
CALENDAR_STATUS_URL = "/calendar/status"
CALENDAR_DISCONNECT_URL = "/calendar/disconnect"
CALENDAR_SYNC_URL = "/calendar/sync"
CALENDAR_EVENTS_URL = "/calendar/events"

BASE_USER = {
    "email": "gcal@example.com",
    "password": "GCalPass123!",
    "full_name": "GCal User",
    "timezone": "UTC",
}


async def _auth(client: AsyncClient) -> dict:
    r = await client.post(SIGNUP_URL, json=BASE_USER)
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── OAuth state unit tests (no HTTP) ─────────────────────────────────────────


def test_oauth_state_encode_decode_roundtrip() -> None:
    """_encode_state / _decode_state must be exact inverses."""
    from app.modules.calendar.router import _decode_state, _encode_state

    user_id = uuid.uuid4()
    state = _encode_state(user_id)
    assert _decode_state(state) == user_id


def test_oauth_state_is_a_jwt_string() -> None:
    from app.modules.calendar.router import _encode_state

    state = _encode_state(uuid.uuid4())
    assert len(state.split(".")) == 3, "OAuth state must be a 3-part JWT"


def test_oauth_state_different_users_produce_different_states() -> None:
    from app.modules.calendar.router import _encode_state

    s1 = _encode_state(uuid.uuid4())
    s2 = _encode_state(uuid.uuid4())
    assert s1 != s2


def test_oauth_state_invalid_string_raises_app_exception() -> None:
    from app.core.exceptions import AppException
    from app.modules.calendar.router import _decode_state

    with pytest.raises(AppException) as exc_info:
        _decode_state("not.a.valid.jwt")
    assert exc_info.value.status_code == 400


def test_oauth_state_tampered_signature_raises() -> None:
    from app.core.exceptions import AppException
    from app.modules.calendar.router import _decode_state, _encode_state

    state = _encode_state(uuid.uuid4())
    parts = state.split(".")
    tampered = parts[0] + "." + parts[1] + ".badsignature"
    with pytest.raises(AppException):
        _decode_state(tampered)


def test_oauth_state_empty_string_raises() -> None:
    from app.core.exceptions import AppException
    from app.modules.calendar.router import _decode_state

    with pytest.raises(AppException):
        _decode_state("")


# ── Endpoint auth guards ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_requires_auth(client: AsyncClient) -> None:
    r = await client.get(CALENDAR_CONNECT_URL)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_status_requires_auth(client: AsyncClient) -> None:
    r = await client.get(CALENDAR_STATUS_URL)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_disconnect_requires_auth(client: AsyncClient) -> None:
    r = await client.delete(CALENDAR_DISCONNECT_URL)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_sync_requires_auth(client: AsyncClient) -> None:
    r = await client.post(CALENDAR_SYNC_URL)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_calendar_events_requires_auth(client: AsyncClient) -> None:
    r = await client.get(CALENDAR_EVENTS_URL)
    assert r.status_code in (401, 403)


# ── Status for new user ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_not_connected_for_new_user(client: AsyncClient) -> None:
    h = await _auth(client)
    r = await client.get(CALENDAR_STATUS_URL, headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["connected"] is False
    assert data.get("google_email") is None


# ── Sync without connection ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_without_google_connection_returns_400(client: AsyncClient) -> None:
    h = await _auth(client)
    r = await client.post(CALENDAR_SYNC_URL, headers=h)
    assert r.status_code == 400
    assert "not connected" in r.json()["detail"].lower()


# ── Connect endpoint (no Google config in test env) ───────────────────────────


@pytest.mark.asyncio
async def test_connect_without_google_config_returns_503(client: AsyncClient) -> None:
    """In test env GOOGLE_CLIENT_ID is empty → 503 "not configured"."""
    h = await _auth(client)
    r = await client.get(CALENDAR_CONNECT_URL, headers=h)
    # 200 if Google is configured in test env, 503 otherwise
    assert r.status_code in (200, 503)
    if r.status_code == 503:
        assert "not configured" in r.json()["detail"].lower()


# ── Calendar events listing ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calendar_events_empty_for_new_user(client: AsyncClient) -> None:
    h = await _auth(client)
    r = await client.get(CALENDAR_EVENTS_URL, headers=h)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_calendar_events_layer_filter_accepts_valid_layer(client: AsyncClient) -> None:
    h = await _auth(client)
    r = await client.get(f"{CALENDAR_EVENTS_URL}?layer=work", headers=h)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── Disconnect ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disconnect_when_not_connected_returns_204(client: AsyncClient) -> None:
    """Disconnecting a user with no Google account must not error."""
    h = await _auth(client)
    r = await client.delete(CALENDAR_DISCONNECT_URL, headers=h)
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_disconnect_clears_status(client: AsyncClient) -> None:
    """After disconnect, status must still return connected=False."""
    h = await _auth(client)
    await client.delete(CALENDAR_DISCONNECT_URL, headers=h)
    status = (await client.get(CALENDAR_STATUS_URL, headers=h)).json()
    assert status["connected"] is False


# ── User isolation ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calendar_status_isolated_between_users(client: AsyncClient) -> None:
    """Two independent users each have their own calendar status."""
    h1_r = await client.post(SIGNUP_URL, json={**BASE_USER, "email": "gcal1@example.com"})
    h2_r = await client.post(SIGNUP_URL, json={**BASE_USER, "email": "gcal2@example.com"})
    h1 = {"Authorization": f"Bearer {h1_r.json()['access_token']}"}
    h2 = {"Authorization": f"Bearer {h2_r.json()['access_token']}"}

    s1 = (await client.get(CALENDAR_STATUS_URL, headers=h1)).json()
    s2 = (await client.get(CALENDAR_STATUS_URL, headers=h2)).json()
    assert s1["connected"] is False
    assert s2["connected"] is False


# ── Repository-level upsert (unit) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calendar_repo_upsert_creates_and_updates(client: AsyncClient) -> None:
    """Inserting the same google_event_id twice must update, not duplicate."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.database import Base
    from app.modules.calendar import repository as repo

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # We need a real user_id — create a User row directly
    import uuid as _uuid
    from app.modules.auth.models import User
    from app.core.security import hash_password

    user_id = _uuid.uuid4()
    async with Session() as session:
        user = User(
            id=user_id,
            email="repo@example.com",
            hashed_password=hash_password("pass"),
            full_name="Repo User",
        )
        session.add(user)
        await session.commit()

    start = datetime(2026, 5, 10, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc)
    gid = "google-event-abc"

    async with Session() as session:
        ev1 = await repo.upsert_event(
            session, user_id, gid, "primary", "First title", None, start, end, False, None
        )
        await session.commit()

    async with Session() as session:
        ev2 = await repo.upsert_event(
            session, user_id, gid, "primary", "Updated title", None, start, end, False, None
        )
        await session.commit()

    async with Session() as session:
        events = await repo.list_events(session, user_id, start, end)

    assert len(events) == 1
    # The UPDATE ran and committed — a fresh query returns the new title
    assert events[0].title == "Updated title"

    await engine.dispose()
