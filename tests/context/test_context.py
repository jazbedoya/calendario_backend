import pytest
from httpx import AsyncClient

SIGNUP_URL = "/auth/signup"
LOGIN_URL = "/auth/login"
CONTEXT_URL = "/context"

USER = {
    "email": "context@example.com",
    "password": "password123",
    "full_name": "Context User",
    "timezone": "America/Bogota",
}

ENTRY_PAYLOAD = {
    "date": "2026-06-01",
    "energy_level": 8,
    "mood": 7,
    "notes": "Productive day",
}


async def _get_token(client: AsyncClient) -> str:
    await client.post(SIGNUP_URL, json=USER)
    resp = await client.post(LOGIN_URL, json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_create_entry(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.post(CONTEXT_URL, json=ENTRY_PAYLOAD, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["date"] == "2026-06-01"
    assert data["energy_level"] == 8
    assert data["mood"] == 7
    assert data["notes"] == "Productive day"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_entry_invalid_energy_level(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {**ENTRY_PAYLOAD, "energy_level": 11}
    response = await client.post(CONTEXT_URL, json=payload, headers=headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_entry_invalid_mood(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {**ENTRY_PAYLOAD, "mood": 0}
    response = await client.post(CONTEXT_URL, json=payload, headers=headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_entries_empty(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get(CONTEXT_URL, headers=headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_entries(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    await client.post(CONTEXT_URL, json=ENTRY_PAYLOAD, headers=headers)
    await client.post(CONTEXT_URL, json={**ENTRY_PAYLOAD, "date": "2026-06-02"}, headers=headers)
    response = await client.get(CONTEXT_URL, headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 2


@pytest.mark.asyncio
async def test_list_entries_filter_by_date_range(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    await client.post(CONTEXT_URL, json={**ENTRY_PAYLOAD, "date": "2026-05-01"}, headers=headers)
    await client.post(CONTEXT_URL, json={**ENTRY_PAYLOAD, "date": "2026-06-01"}, headers=headers)
    await client.post(CONTEXT_URL, json={**ENTRY_PAYLOAD, "date": "2026-07-01"}, headers=headers)
    response = await client.get(f"{CONTEXT_URL}?start=2026-05-15&end=2026-06-15", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["date"] == "2026-06-01"


@pytest.mark.asyncio
async def test_get_entry(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = (await client.post(CONTEXT_URL, json=ENTRY_PAYLOAD, headers=headers)).json()
    response = await client.get(f"{CONTEXT_URL}/{created['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_get_entry_not_found(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get(f"{CONTEXT_URL}/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_entry(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = (await client.post(CONTEXT_URL, json=ENTRY_PAYLOAD, headers=headers)).json()
    response = await client.put(
        f"{CONTEXT_URL}/{created['id']}",
        json={"energy_level": 5, "mood": 6},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["energy_level"] == 5
    assert data["mood"] == 6


@pytest.mark.asyncio
async def test_update_entry_not_found(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.put(
        f"{CONTEXT_URL}/00000000-0000-0000-0000-000000000000",
        json={"energy_level": 5},
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_entry(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = (await client.post(CONTEXT_URL, json=ENTRY_PAYLOAD, headers=headers)).json()
    response = await client.delete(f"{CONTEXT_URL}/{created['id']}", headers=headers)
    assert response.status_code == 204
    get_resp = await client.get(f"{CONTEXT_URL}/{created['id']}", headers=headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_entry_not_found(client: AsyncClient) -> None:
    token = await _get_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.delete(f"{CONTEXT_URL}/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_entries_isolated_between_users(client: AsyncClient) -> None:
    await client.post(SIGNUP_URL, json=USER)
    token_a = (
        await client.post(LOGIN_URL, json={"email": USER["email"], "password": USER["password"]})
    ).json()["access_token"]

    user_b = {**USER, "email": "ctx_b@example.com"}
    await client.post(SIGNUP_URL, json=user_b)
    token_b = (
        await client.post(LOGIN_URL, json={"email": user_b["email"], "password": USER["password"]})
    ).json()["access_token"]

    created = (
        await client.post(CONTEXT_URL, json=ENTRY_PAYLOAD, headers={"Authorization": f"Bearer {token_a}"})
    ).json()

    resp = await client.get(f"{CONTEXT_URL}/{created['id']}", headers={"Authorization": f"Bearer {token_b}"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_entry_requires_auth(client: AsyncClient) -> None:
    response = await client.post(CONTEXT_URL, json=ENTRY_PAYLOAD)
    assert response.status_code in (401, 403)
