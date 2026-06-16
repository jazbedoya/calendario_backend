"""
Integration tests: PATCH /auth/me — update full_name, timezone, mascot_name.
"""
import pytest
from httpx import AsyncClient

from tests.conftest import _captured_tokens

SIGNUP_URL = "/auth/signup"
VERIFY_URL = "/auth/verify"
LOGIN_URL = "/auth/login"
ME_URL = "/auth/me"
PATCH_ME_URL = "/auth/me"

BASE_USER = {
    "email": "patch@example.com",
    "password": "PatchPass123!",
    "full_name": "Original Name",
    "timezone": "UTC",
}


async def _signup_and_auth(client: AsyncClient) -> dict:
    r = await client.post(SIGNUP_URL, json=BASE_USER)
    assert r.status_code == 202
    token = _captured_tokens.get(BASE_USER["email"])
    assert token
    await client.get(f"{VERIFY_URL}?token={token}")
    lr = await client.post(LOGIN_URL, json={"email": BASE_USER["email"], "password": BASE_USER["password"]})
    assert lr.status_code == 200
    return lr.json()


def _auth_headers(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# ── GET /me returns mascot_name ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_me_returns_default_mascot_name(client: AsyncClient) -> None:
    tokens = await _signup_and_auth(client)
    r = await client.get(ME_URL, headers=_auth_headers(tokens))
    assert r.status_code == 200
    assert r.json()["mascot_name"] == "Tuga"


# ── PATCH /auth/me ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_mascot_name(client: AsyncClient) -> None:
    tokens = await _signup_and_auth(client)
    r = await client.patch(
        PATCH_ME_URL,
        json={"mascot_name": "Shelby"},
        headers=_auth_headers(tokens),
    )
    assert r.status_code == 200
    assert r.json()["mascot_name"] == "Shelby"


@pytest.mark.asyncio
async def test_patch_mascot_name_persisted(client: AsyncClient) -> None:
    tokens = await _signup_and_auth(client)
    await client.patch(
        PATCH_ME_URL,
        json={"mascot_name": "Tortu"},
        headers=_auth_headers(tokens),
    )
    r = await client.get(ME_URL, headers=_auth_headers(tokens))
    assert r.json()["mascot_name"] == "Tortu"


@pytest.mark.asyncio
async def test_patch_full_name(client: AsyncClient) -> None:
    tokens = await _signup_and_auth(client)
    r = await client.patch(
        PATCH_ME_URL,
        json={"full_name": "Updated Name"},
        headers=_auth_headers(tokens),
    )
    assert r.status_code == 200
    assert r.json()["full_name"] == "Updated Name"


@pytest.mark.asyncio
async def test_patch_timezone(client: AsyncClient) -> None:
    tokens = await _signup_and_auth(client)
    r = await client.patch(
        PATCH_ME_URL,
        json={"timezone": "America/New_York"},
        headers=_auth_headers(tokens),
    )
    assert r.status_code == 200
    assert r.json()["timezone"] == "America/New_York"


@pytest.mark.asyncio
async def test_patch_multiple_fields_at_once(client: AsyncClient) -> None:
    tokens = await _signup_and_auth(client)
    r = await client.patch(
        PATCH_ME_URL,
        json={"full_name": "New Name", "timezone": "Asia/Tokyo", "mascot_name": "Kame"},
        headers=_auth_headers(tokens),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == "New Name"
    assert body["timezone"] == "Asia/Tokyo"
    assert body["mascot_name"] == "Kame"


@pytest.mark.asyncio
async def test_patch_empty_body_changes_nothing(client: AsyncClient) -> None:
    tokens = await _signup_and_auth(client)
    r = await client.patch(PATCH_ME_URL, json={}, headers=_auth_headers(tokens))
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == BASE_USER["full_name"]
    assert body["mascot_name"] == "Tuga"


@pytest.mark.asyncio
async def test_patch_me_requires_auth(client: AsyncClient) -> None:
    r = await client.patch(PATCH_ME_URL, json={"mascot_name": "X"})
    assert r.status_code == 403
