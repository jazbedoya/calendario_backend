import pytest
from httpx import AsyncClient

SIGNUP_URL = "/auth/signup"
LOGIN_URL = "/auth/login"
EVENTS_URL = "/events"

USER = {
    "email": "events@example.com",
    "password": "password123",
    "full_name": "Events User",
    "timezone": "America/Bogota",
}

EVENT_PAYLOAD = {
    "title": "Team Meeting",
    "description": "Weekly sync",
    "start_at": "2026-06-01T10:00:00Z",
    "end_at": "2026-06-01T11:00:00Z",
    "is_all_day": False,
    "location": "Office",
    "layer": "work",
}


async def _get_token(client: AsyncClient) -> str:
    await client.post(SIGNUP_URL, json=USER)
    resp = await client.post(LOGIN_URL, json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_create_event(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.post(EVENTS_URL, json=EVENT_PAYLOAD, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Team Meeting"
    assert data["layer"] == "work"
    assert data["source"] == "manual"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_event_invalid_dates(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {**EVENT_PAYLOAD, "start_at": "2026-06-01T11:00:00Z", "end_at": "2026-06-01T10:00:00Z"}
    response = await client.post(EVENTS_URL, json=payload, headers=headers)
    assert response.status_code == 400
    assert "end_at" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_events_empty(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get(EVENTS_URL, headers=headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_events(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    await client.post(EVENTS_URL, json=EVENT_PAYLOAD, headers=headers)
    await client.post(EVENTS_URL, json={**EVENT_PAYLOAD, "title": "Event 2"}, headers=headers)
    response = await client.get(EVENTS_URL, headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 2


@pytest.mark.asyncio
async def test_list_events_filter_by_layer(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    await client.post(EVENTS_URL, json=EVENT_PAYLOAD, headers=headers)
    await client.post(EVENTS_URL, json={**EVENT_PAYLOAD, "layer": "personal"}, headers=headers)
    response = await client.get(f"{EVENTS_URL}?layer=work", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["layer"] == "work"


@pytest.mark.asyncio
async def test_get_event(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = (await client.post(EVENTS_URL, json=EVENT_PAYLOAD, headers=headers)).json()
    response = await client.get(f"{EVENTS_URL}/{created['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_get_event_not_found(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get(f"{EVENTS_URL}/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_event(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = (await client.post(EVENTS_URL, json=EVENT_PAYLOAD, headers=headers)).json()
    response = await client.put(
        f"{EVENTS_URL}/{created['id']}",
        json={"title": "Updated Title"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Updated Title"


@pytest.mark.asyncio
async def test_update_event_not_found(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.put(
        f"{EVENTS_URL}/00000000-0000-0000-0000-000000000000",
        json={"title": "X"},
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_event(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = (await client.post(EVENTS_URL, json=EVENT_PAYLOAD, headers=headers)).json()
    response = await client.delete(f"{EVENTS_URL}/{created['id']}", headers=headers)
    assert response.status_code == 204
    # Confirm gone
    get_resp = await client.get(f"{EVENTS_URL}/{created['id']}", headers=headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_event_not_found(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.delete(f"{EVENTS_URL}/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_events_isolated_between_users(client: AsyncClient) -> None:
    # User A
    await client.post(SIGNUP_URL, json=USER)
    token_a = (
        await client.post(LOGIN_URL, json={"email": USER["email"], "password": USER["password"]})
    ).json()["access_token"]

    # User B
    user_b = {**USER, "email": "b@example.com"}
    await client.post(SIGNUP_URL, json=user_b)
    token_b = (
        await client.post(LOGIN_URL, json={"email": user_b["email"], "password": USER["password"]})
    ).json()["access_token"]

    # A creates event
    created = (
        await client.post(EVENTS_URL, json=EVENT_PAYLOAD, headers={"Authorization": f"Bearer {token_a}"})
    ).json()

    # B cannot see it
    resp = await client.get(f"{EVENTS_URL}/{created['id']}", headers={"Authorization": f"Bearer {token_b}"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_event_requires_auth(client: AsyncClient) -> None:
    response = await client.post(EVENTS_URL, json=EVENT_PAYLOAD)
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_delete_event_hidden_from_list(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = (await client.post(EVENTS_URL, json=EVENT_PAYLOAD, headers=headers)).json()
    await client.post(EVENTS_URL, json={**EVENT_PAYLOAD, "title": "Keep me"}, headers=headers)
    # Delete the first event
    del_resp = await client.delete(f"{EVENTS_URL}/{created['id']}", headers=headers)
    assert del_resp.status_code == 204
    # Deleted event should not appear in list
    list_resp = await client.get(EVENTS_URL, headers=headers)
    assert list_resp.status_code == 200
    ids = [e["id"] for e in list_resp.json()]
    assert created["id"] not in ids
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_delete_event_idempotent_returns_404(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = (await client.post(EVENTS_URL, json=EVENT_PAYLOAD, headers=headers)).json()
    await client.delete(f"{EVENTS_URL}/{created['id']}", headers=headers)
    # Second delete should 404 (event already soft-deleted)
    resp = await client.delete(f"{EVENTS_URL}/{created['id']}", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_restore_event(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = (await client.post(EVENTS_URL, json=EVENT_PAYLOAD, headers=headers)).json()
    await client.delete(f"{EVENTS_URL}/{created['id']}", headers=headers)
    # Restore
    restore_resp = await client.post(f"{EVENTS_URL}/{created['id']}/restore", headers=headers)
    assert restore_resp.status_code == 200
    assert restore_resp.json()["id"] == created["id"]
    # Now visible again
    get_resp = await client.get(f"{EVENTS_URL}/{created['id']}", headers=headers)
    assert get_resp.status_code == 200


@pytest.mark.asyncio
async def test_restore_non_deleted_event_returns_404(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = (await client.post(EVENTS_URL, json=EVENT_PAYLOAD, headers=headers)).json()
    resp = await client.post(f"{EVENTS_URL}/{created['id']}/restore", headers=headers)
    assert resp.status_code == 404
