"""
Integration tests: events — CRUD, soft-delete/restore, cross-user isolation,
layer/date filters, overlapping events.
"""
import pytest
from httpx import AsyncClient

from tests.conftest import _captured_tokens

SIGNUP_URL = "/auth/signup"
VERIFY_URL = "/auth/verify"
LOGIN_URL = "/auth/login"
EVENTS_URL = "/events"


def _user(email: str) -> dict:
    return {"email": email, "password": "EPass123!", "full_name": "Events User", "timezone": "UTC"}


async def _auth(client: AsyncClient, email: str = "events@example.com") -> dict:
    r = await client.post(SIGNUP_URL, json=_user(email))
    assert r.status_code == 202
    token = _captured_tokens.get(email)
    assert token
    await client.get(f"{VERIFY_URL}?token={token}")
    lr = await client.post(LOGIN_URL, json={"email": email, "password": "EPass123!"})
    assert lr.status_code == 200
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}


def _ev(
    title: str = "Meeting",
    start: str = "2026-05-10T09:00:00Z",
    end: str = "2026-05-10T10:00:00Z",
    layer: str = "work",
) -> dict:
    return {"title": title, "start_at": start, "end_at": end, "layer": layer}


# ── Basic CRUD ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_event_returns_201_with_fields(client: AsyncClient) -> None:
    h = await _auth(client)
    r = await client.post(EVENTS_URL, json=_ev(), headers=h)
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "Meeting"
    assert data["layer"] == "work"
    assert "id" in data
    assert data["source"] == "manual"


@pytest.mark.asyncio
async def test_list_events_returns_created_event(client: AsyncClient) -> None:
    h = await _auth(client)
    await client.post(EVENTS_URL, json=_ev(), headers=h)
    r = await client.get(EVENTS_URL, headers=h)
    assert r.status_code == 200
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_get_event_by_id(client: AsyncClient) -> None:
    h = await _auth(client)
    created = (await client.post(EVENTS_URL, json=_ev(), headers=h)).json()
    r = await client.get(f"{EVENTS_URL}/{created['id']}", headers=h)
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_get_nonexistent_event_returns_404(client: AsyncClient) -> None:
    h = await _auth(client)
    r = await client.get(f"{EVENTS_URL}/00000000-0000-0000-0000-000000000001", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_event_layer(client: AsyncClient) -> None:
    h = await _auth(client)
    ev = (await client.post(EVENTS_URL, json=_ev(), headers=h)).json()
    r = await client.put(f"{EVENTS_URL}/{ev['id']}", json={"layer": "family"}, headers=h)
    assert r.status_code == 200
    assert r.json()["layer"] == "family"


@pytest.mark.asyncio
async def test_update_event_title(client: AsyncClient) -> None:
    h = await _auth(client)
    ev = (await client.post(EVENTS_URL, json=_ev(), headers=h)).json()
    r = await client.put(f"{EVENTS_URL}/{ev['id']}", json={"title": "Renamed"}, headers=h)
    assert r.status_code == 200
    assert r.json()["title"] == "Renamed"


@pytest.mark.asyncio
async def test_end_before_start_rejected(client: AsyncClient) -> None:
    h = await _auth(client)
    r = await client.post(
        EVENTS_URL,
        json=_ev(start="2026-05-10T11:00:00Z", end="2026-05-10T09:00:00Z"),
        headers=h,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_all_day_event_is_stored(client: AsyncClient) -> None:
    h = await _auth(client)
    r = await client.post(EVENTS_URL, json={**_ev(), "is_all_day": True}, headers=h)
    assert r.status_code == 201
    assert r.json()["is_all_day"] is True


# ── Soft delete + restore ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_returns_204(client: AsyncClient) -> None:
    h = await _auth(client)
    ev = (await client.post(EVENTS_URL, json=_ev(), headers=h)).json()
    r = await client.delete(f"{EVENTS_URL}/{ev['id']}", headers=h)
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_delete_hides_event_from_list(client: AsyncClient) -> None:
    h = await _auth(client)
    ev = (await client.post(EVENTS_URL, json=_ev(), headers=h)).json()
    await client.delete(f"{EVENTS_URL}/{ev['id']}", headers=h)
    ids = [e["id"] for e in (await client.get(EVENTS_URL, headers=h)).json()]
    assert ev["id"] not in ids


@pytest.mark.asyncio
async def test_delete_hides_event_from_get_by_id(client: AsyncClient) -> None:
    h = await _auth(client)
    ev = (await client.post(EVENTS_URL, json=_ev(), headers=h)).json()
    await client.delete(f"{EVENTS_URL}/{ev['id']}", headers=h)
    r = await client.get(f"{EVENTS_URL}/{ev['id']}", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_double_delete_returns_404(client: AsyncClient) -> None:
    """Second DELETE on an already-soft-deleted event returns 404."""
    h = await _auth(client)
    ev = (await client.post(EVENTS_URL, json=_ev(), headers=h)).json()
    await client.delete(f"{EVENTS_URL}/{ev['id']}", headers=h)
    r = await client.delete(f"{EVENTS_URL}/{ev['id']}", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_restore_makes_event_visible_again(client: AsyncClient) -> None:
    h = await _auth(client)
    ev = (await client.post(EVENTS_URL, json=_ev(), headers=h)).json()
    await client.delete(f"{EVENTS_URL}/{ev['id']}", headers=h)
    r = await client.post(f"{EVENTS_URL}/{ev['id']}/restore", headers=h)
    assert r.status_code == 200
    listed = (await client.get(EVENTS_URL, headers=h)).json()
    assert any(e["id"] == ev["id"] for e in listed)


@pytest.mark.asyncio
async def test_restore_non_deleted_event_returns_404(client: AsyncClient) -> None:
    h = await _auth(client)
    ev = (await client.post(EVENTS_URL, json=_ev(), headers=h)).json()
    r = await client.post(f"{EVENTS_URL}/{ev['id']}/restore", headers=h)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_then_restore_then_delete_again(client: AsyncClient) -> None:
    """Full soft-delete lifecycle: delete → restore → delete again."""
    h = await _auth(client)
    ev = (await client.post(EVENTS_URL, json=_ev(), headers=h)).json()
    await client.delete(f"{EVENTS_URL}/{ev['id']}", headers=h)
    await client.post(f"{EVENTS_URL}/{ev['id']}/restore", headers=h)
    r = await client.delete(f"{EVENTS_URL}/{ev['id']}", headers=h)
    assert r.status_code == 204
    listed = (await client.get(EVENTS_URL, headers=h)).json()
    assert not any(e["id"] == ev["id"] for e in listed)


# ── Overlapping events ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overlapping_events_both_stored(client: AsyncClient) -> None:
    """No server-side conflict prevention — both overlapping events must be persisted."""
    h = await _auth(client)
    e1 = _ev("A", "2026-05-10T09:00:00Z", "2026-05-10T10:30:00Z")
    e2 = _ev("B", "2026-05-10T09:45:00Z", "2026-05-10T11:00:00Z")
    r1 = await client.post(EVENTS_URL, json=e1, headers=h)
    r2 = await client.post(EVENTS_URL, json=e2, headers=h)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert len((await client.get(EVENTS_URL, headers=h)).json()) == 2


@pytest.mark.asyncio
async def test_back_to_back_events_both_stored(client: AsyncClient) -> None:
    """Events touching at the same boundary minute are both valid."""
    h = await _auth(client)
    await client.post(EVENTS_URL, json=_ev("A", "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z"), headers=h)
    await client.post(EVENTS_URL, json=_ev("B", "2026-05-10T10:00:00Z", "2026-05-10T11:00:00Z"), headers=h)
    assert len((await client.get(EVENTS_URL, headers=h)).json()) == 2


@pytest.mark.asyncio
async def test_same_day_different_layers_both_stored(client: AsyncClient) -> None:
    h = await _auth(client)
    await client.post(EVENTS_URL, json=_ev("Work", "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z", "work"), headers=h)
    await client.post(EVENTS_URL, json=_ev("Family", "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z", "family"), headers=h)
    assert len((await client.get(EVENTS_URL, headers=h)).json()) == 2


# ── Cross-user isolation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_events_not_visible_to_other_user(client: AsyncClient) -> None:
    h1 = await _auth(client, "user1@example.com")
    h2 = await _auth(client, "user2@example.com")
    await client.post(EVENTS_URL, json=_ev("Private"), headers=h1)
    assert (await client.get(EVENTS_URL, headers=h2)).json() == []


@pytest.mark.asyncio
async def test_user_cannot_get_other_users_event_by_id(client: AsyncClient) -> None:
    h1 = await _auth(client, "owner@example.com")
    h2 = await _auth(client, "spy@example.com")
    ev = (await client.post(EVENTS_URL, json=_ev(), headers=h1)).json()
    r = await client.get(f"{EVENTS_URL}/{ev['id']}", headers=h2)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_update_other_users_event(client: AsyncClient) -> None:
    h1 = await _auth(client, "owner2@example.com")
    h2 = await _auth(client, "attacker@example.com")
    ev = (await client.post(EVENTS_URL, json=_ev(), headers=h1)).json()
    r = await client.put(f"{EVENTS_URL}/{ev['id']}", json={"title": "Hacked"}, headers=h2)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_delete_other_users_event(client: AsyncClient) -> None:
    h1 = await _auth(client, "owner3@example.com")
    h2 = await _auth(client, "attacker2@example.com")
    ev = (await client.post(EVENTS_URL, json=_ev(), headers=h1)).json()
    r = await client.delete(f"{EVENTS_URL}/{ev['id']}", headers=h2)
    assert r.status_code == 404


# ── Layer / date filters ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_by_layer_family(client: AsyncClient) -> None:
    h = await _auth(client)
    await client.post(EVENTS_URL, json=_ev("Work", layer="work"), headers=h)
    await client.post(EVENTS_URL, json=_ev("Family", layer="family"), headers=h)
    result = (await client.get(f"{EVENTS_URL}?layer=family", headers=h)).json()
    assert len(result) == 1
    assert result[0]["layer"] == "family"


@pytest.mark.asyncio
async def test_filter_by_layer_returns_nothing_when_no_match(client: AsyncClient) -> None:
    h = await _auth(client)
    await client.post(EVENTS_URL, json=_ev("Work", layer="work"), headers=h)
    result = (await client.get(f"{EVENTS_URL}?layer=personal", headers=h)).json()
    assert result == []


@pytest.mark.asyncio
async def test_filter_by_date_range_excludes_outside_events(client: AsyncClient) -> None:
    h = await _auth(client)
    await client.post(EVENTS_URL, json=_ev("May", "2026-05-15T09:00:00Z", "2026-05-15T10:00:00Z"), headers=h)
    await client.post(EVENTS_URL, json=_ev("June", "2026-06-15T09:00:00Z", "2026-06-15T10:00:00Z"), headers=h)
    result = (await client.get(
        f"{EVENTS_URL}?start=2026-05-01T00:00:00Z&end=2026-05-31T23:59:59Z",
        headers=h,
    )).json()
    titles = [e["title"] for e in result]
    assert "May" in titles
    assert "June" not in titles


@pytest.mark.asyncio
async def test_events_ordered_by_start_at(client: AsyncClient) -> None:
    h = await _auth(client)
    await client.post(EVENTS_URL, json=_ev("Late", "2026-05-10T14:00:00Z", "2026-05-10T15:00:00Z"), headers=h)
    await client.post(EVENTS_URL, json=_ev("Early", "2026-05-10T08:00:00Z", "2026-05-10T09:00:00Z"), headers=h)
    result = (await client.get(EVENTS_URL, headers=h)).json()
    assert result[0]["title"] == "Early"
    assert result[1]["title"] == "Late"
