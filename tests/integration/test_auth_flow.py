"""
Integration tests: auth flow — JWT structure, token lifecycle, protected routes matrix.
"""
import pytest
from httpx import AsyncClient
from jose import jwt

from app.config import settings
from app.core.security import ALGORITHM

SIGNUP_URL = "/auth/signup"
LOGIN_URL = "/auth/login"
REFRESH_URL = "/auth/refresh"
ME_URL = "/auth/me"
LOGOUT_URL = "/auth/logout"

BASE_USER = {
    "email": "flow@example.com",
    "password": "FlowPass123!",
    "full_name": "Flow User",
    "timezone": "Europe/Madrid",
}


async def _signup(client: AsyncClient, email: str = BASE_USER["email"]) -> dict:
    r = await client.post(SIGNUP_URL, json={**BASE_USER, "email": email})
    assert r.status_code == 201
    return r.json()


# ── JWT structure ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_access_token_has_three_parts(client: AsyncClient) -> None:
    tokens = await _signup(client)
    parts = tokens["access_token"].split(".")
    assert len(parts) == 3, "JWT must have header.payload.signature"


@pytest.mark.asyncio
async def test_access_token_claims(client: AsyncClient) -> None:
    tokens = await _signup(client)
    payload = jwt.decode(tokens["access_token"], settings.secret_key, algorithms=[ALGORITHM])
    assert "sub" in payload
    assert payload.get("type") == "access"
    assert "exp" in payload


@pytest.mark.asyncio
async def test_access_token_sub_matches_me_id(client: AsyncClient) -> None:
    tokens = await _signup(client)
    payload = jwt.decode(tokens["access_token"], settings.secret_key, algorithms=[ALGORITHM])
    me = await client.get(ME_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.json()["id"] == payload["sub"]


@pytest.mark.asyncio
async def test_two_users_have_different_token_subs(client: AsyncClient) -> None:
    t1 = await _signup(client, "a@example.com")
    t2 = await _signup(client, "b@example.com")
    p1 = jwt.decode(t1["access_token"], settings.secret_key, algorithms=[ALGORITHM])
    p2 = jwt.decode(t2["access_token"], settings.secret_key, algorithms=[ALGORITHM])
    assert p1["sub"] != p2["sub"]


# ── Protected routes matrix ───────────────────────────────────────────────────


PROTECTED_ROUTES = [
    ("GET", "/auth/me"),
    ("GET", "/events"),
    ("POST", "/events"),
    ("GET", "/stats/monthly?year=2026&month=5"),
    ("GET", "/calendar/status"),
    ("POST", "/calendar/sync"),
    ("GET", "/context"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
async def test_protected_route_without_token_returns_4xx(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, path)
    assert response.status_code in (401, 403), f"{method} {path} must require auth, got {response.status_code}"


@pytest.mark.asyncio
async def test_wrong_auth_scheme_rejected(client: AsyncClient) -> None:
    tokens = await _signup(client)
    # "Token" prefix instead of "Bearer"
    r = await client.get(ME_URL, headers={"Authorization": f"Token {tokens['access_token']}"})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_tampered_token_signature_rejected(client: AsyncClient) -> None:
    tokens = await _signup(client)
    parts = tokens["access_token"].split(".")
    tampered = parts[0] + "." + parts[1] + ".invalidsignature"
    r = await client.get(ME_URL, headers={"Authorization": f"Bearer {tampered}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_garbage_token_rejected(client: AsyncClient) -> None:
    r = await client.get(ME_URL, headers={"Authorization": "Bearer notavalidjwtatall"})
    assert r.status_code == 401


# ── Token lifecycle ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_rotation_chain(client: AsyncClient) -> None:
    """Rotate refresh token 3 times — each step produces a working new token."""
    tokens = await _signup(client)
    current = tokens["refresh_token"]
    for _ in range(3):
        r = await client.post(REFRESH_URL, json={"refresh_token": current})
        assert r.status_code == 200
        new_token = r.json()["refresh_token"]
        assert new_token != current
        current = new_token


@pytest.mark.asyncio
async def test_used_refresh_token_cannot_be_reused(client: AsyncClient) -> None:
    tokens = await _signup(client)
    old = tokens["refresh_token"]
    await client.post(REFRESH_URL, json={"refresh_token": old})
    r = await client.post(REFRESH_URL, json={"refresh_token": old})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout_invalidates_refresh_token(client: AsyncClient) -> None:
    tokens = await _signup(client)
    await client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    r = await client.post(REFRESH_URL, json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_access_token_stays_valid_after_logout_by_design(client: AsyncClient) -> None:
    """Access tokens are stateless JWTs — valid until expiry even after logout (by design)."""
    tokens = await _signup(client)
    await client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    r = await client.get(ME_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_each_login_produces_unique_refresh_token(client: AsyncClient) -> None:
    await _signup(client)
    creds = {"email": BASE_USER["email"], "password": BASE_USER["password"]}
    r1 = await client.post(LOGIN_URL, json=creds)
    r2 = await client.post(LOGIN_URL, json=creds)
    assert r1.json()["refresh_token"] != r2.json()["refresh_token"]


@pytest.mark.asyncio
async def test_logout_revokes_all_sessions(client: AsyncClient) -> None:
    """Logging out revokes ALL refresh tokens for that user across all sessions."""
    await _signup(client)
    creds = {"email": BASE_USER["email"], "password": BASE_USER["password"]}
    s1 = (await client.post(LOGIN_URL, json=creds)).json()
    s2 = (await client.post(LOGIN_URL, json=creds)).json()

    # Logout using session1's access token
    await client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {s1['access_token']}"})

    # session2's refresh token should also be revoked
    r = await client.post(REFRESH_URL, json={"refresh_token": s2["refresh_token"]})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_rotated_refresh_token_is_usable(client: AsyncClient) -> None:
    tokens = await _signup(client)
    rotate = (await client.post(REFRESH_URL, json={"refresh_token": tokens["refresh_token"]})).json()
    r = await client.post(REFRESH_URL, json={"refresh_token": rotate["refresh_token"]})
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_me_returns_timezone_set_at_signup(client: AsyncClient) -> None:
    tokens = await _signup(client)
    r = await client.get(ME_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.json()["timezone"] == BASE_USER["timezone"]
