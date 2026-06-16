"""
Integration tests: Google Calendar OAuth state encoding, endpoint auth guards,
calendar status, sync without connection, calendar events listing.
"""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from tests.conftest import _captured_tokens

SIGNUP_URL = "/auth/signup"
VERIFY_URL = "/auth/verify"
LOGIN_URL = "/auth/login"
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


async def _auth(client: AsyncClient, email: str = BASE_USER["email"]) -> dict:
    r = await client.post(SIGNUP_URL, json={**BASE_USER, "email": email})
    assert r.status_code == 202
    token = _captured_tokens.get(email)
    assert token
    await client.get(f"{VERIFY_URL}?token={token}")
    lr = await client.post(LOGIN_URL, json={"email": email, "password": BASE_USER["password"]})
    assert lr.status_code == 200
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}


# ── OAuth state (unit, no HTTP) ───────────────────────────────────────────────


def test_oauth_state_is_a_jwt_string() -> None:
    from app.modules.calendar.router import _encode_state

    state = _encode_state(uuid.uuid4(), "avante://callback", "https://example.com/cb")
    assert len(state.split(".")) == 3, "OAuth state must be a 3-part JWT"


def test_oauth_state_different_users_produce_different_states() -> None:
    from app.modules.calendar.router import _encode_state

    s1 = _encode_state(uuid.uuid4(), "avante://callback", "https://example.com/cb")
    s2 = _encode_state(uuid.uuid4(), "avante://callback", "https://example.com/cb")
    assert s1 != s2


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


# ── Connect endpoint ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_returns_url(client: AsyncClient) -> None:
    h = await _auth(client)
    r = await client.get(CALENDAR_CONNECT_URL, headers=h)
    assert r.status_code == 200
    assert "url" in r.json()


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
    h = await _auth(client)
    r = await client.delete(CALENDAR_DISCONNECT_URL, headers=h)
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_disconnect_clears_status(client: AsyncClient) -> None:
    h = await _auth(client)
    await client.delete(CALENDAR_DISCONNECT_URL, headers=h)
    status = (await client.get(CALENDAR_STATUS_URL, headers=h)).json()
    assert status["connected"] is False


# ── User isolation ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calendar_status_isolated_between_users(client: AsyncClient) -> None:
    h1 = await _auth(client, "gcal1@example.com")
    h2 = await _auth(client, "gcal2@example.com")

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
        await repo.upsert_event(
            session, user_id, gid, "primary", "First title", None, start, end, False, None
        )
        await session.commit()

    async with Session() as session:
        await repo.upsert_event(
            session, user_id, gid, "primary", "Updated title", None, start, end, False, None
        )
        await session.commit()

    async with Session() as session:
        events = await repo.list_events(session, user_id, start, end)

    assert len(events) == 1
    assert events[0].title == "Updated title"

    await engine.dispose()
