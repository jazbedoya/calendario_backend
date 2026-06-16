import pytest
from httpx import AsyncClient

SIGNUP_URL = "/auth/signup"
VERIFY_URL = "/auth/verify"
LOGIN_URL = "/auth/login"
REFRESH_URL = "/auth/refresh"
ME_URL = "/auth/me"
LOGOUT_URL = "/auth/logout"

VALID_USER = {
    "email": "test@example.com",
    "password": "securepassword123",
    "full_name": "Test User",
    "timezone": "America/Bogota",
}


async def _signup_and_login(client: AsyncClient, captured: dict, user: dict = VALID_USER) -> dict:
    """Sign up, verify email, login, return tokens dict."""
    r = await client.post(SIGNUP_URL, json=user)
    assert r.status_code == 202

    token = captured.get(user["email"])
    assert token
    await client.get(f"{VERIFY_URL}?token={token}")

    lr = await client.post(LOGIN_URL, json={"email": user["email"], "password": user["password"]})
    assert lr.status_code == 200
    return lr.json()


# ── signup ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signup_success(client: AsyncClient) -> None:
    response = await client.post(SIGNUP_URL, json=VALID_USER)
    assert response.status_code == 202
    assert response.json()["email"] == VALID_USER["email"]


@pytest.mark.asyncio
async def test_signup_duplicate_email(client: AsyncClient, captured_tokens: dict) -> None:
    await _signup_and_login(client, captured_tokens)
    response = await client.post(SIGNUP_URL, json=VALID_USER)
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]


@pytest.mark.asyncio
async def test_signup_invalid_email(client: AsyncClient) -> None:
    response = await client.post(SIGNUP_URL, json={**VALID_USER, "email": "not-an-email"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_signup_missing_email(client: AsyncClient) -> None:
    user = {k: v for k, v in VALID_USER.items() if k != "email"}
    response = await client.post(SIGNUP_URL, json=user)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_signup_missing_password(client: AsyncClient) -> None:
    user = {k: v for k, v in VALID_USER.items() if k != "password"}
    response = await client.post(SIGNUP_URL, json=user)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_signup_missing_full_name(client: AsyncClient) -> None:
    user = {k: v for k, v in VALID_USER.items() if k != "full_name"}
    response = await client.post(SIGNUP_URL, json=user)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_signup_without_timezone_uses_default(client: AsyncClient) -> None:
    user = {k: v for k, v in VALID_USER.items() if k != "timezone"}
    response = await client.post(SIGNUP_URL, json=user)
    assert response.status_code == 202


# ── login ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_before_verification_returns_403(client: AsyncClient) -> None:
    await client.post(SIGNUP_URL, json=VALID_USER)
    response = await client.post(
        LOGIN_URL,
        json={"email": VALID_USER["email"], "password": VALID_USER["password"]},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, captured_tokens: dict) -> None:
    tokens = await _signup_and_login(client, captured_tokens)
    assert "access_token" in tokens
    assert "refresh_token" in tokens


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, captured_tokens: dict) -> None:
    await _signup_and_login(client, captured_tokens)
    response = await client.post(
        LOGIN_URL,
        json={"email": VALID_USER["email"], "password": "wrongpassword"},
    )
    assert response.status_code == 401
    assert "Invalid credentials" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient) -> None:
    response = await client.post(
        LOGIN_URL,
        json={"email": "nobody@example.com", "password": "whatever"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_each_call_returns_new_refresh_token(client: AsyncClient, captured_tokens: dict) -> None:
    await _signup_and_login(client, captured_tokens)
    creds = {"email": VALID_USER["email"], "password": VALID_USER["password"]}
    r1 = await client.post(LOGIN_URL, json=creds)
    r2 = await client.post(LOGIN_URL, json=creds)
    assert r1.json()["refresh_token"] != r2.json()["refresh_token"]


# ── me ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_me_success(client: AsyncClient, captured_tokens: dict) -> None:
    tokens = await _signup_and_login(client, captured_tokens)
    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == VALID_USER["email"]
    assert data["full_name"] == VALID_USER["full_name"]


@pytest.mark.asyncio
async def test_me_no_token(client: AsyncClient) -> None:
    response = await client.get(ME_URL)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_me_invalid_token(client: AsyncClient) -> None:
    response = await client.get(ME_URL, headers={"Authorization": "Bearer invalidtoken"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_does_not_expose_password(client: AsyncClient, captured_tokens: dict) -> None:
    tokens = await _signup_and_login(client, captured_tokens)
    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    data = response.json()
    assert "password" not in data
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_me_returns_correct_fields(client: AsyncClient, captured_tokens: dict) -> None:
    tokens = await _signup_and_login(client, captured_tokens)
    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    data = response.json()
    assert "id" in data
    assert data["email"] == VALID_USER["email"]
    assert data["full_name"] == VALID_USER["full_name"]
    assert data["timezone"] == VALID_USER["timezone"]


@pytest.mark.asyncio
async def test_me_access_token_valid_after_logout(client: AsyncClient, captured_tokens: dict) -> None:
    """Logout revoca el refresh token, pero el access token sigue válido hasta expirar."""
    tokens = await _signup_and_login(client, captured_tokens)
    await client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    response = await client.get(ME_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert response.status_code == 200


# ── refresh ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_success(client: AsyncClient, captured_tokens: dict) -> None:
    tokens = await _signup_and_login(client, captured_tokens)
    response = await client.post(REFRESH_URL, json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["refresh_token"] != tokens["refresh_token"]


@pytest.mark.asyncio
async def test_refresh_reuse_fails(client: AsyncClient, captured_tokens: dict) -> None:
    tokens = await _signup_and_login(client, captured_tokens)
    await client.post(REFRESH_URL, json={"refresh_token": tokens["refresh_token"]})
    response = await client.post(REFRESH_URL, json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_invalid_token(client: AsyncClient) -> None:
    response = await client.post(REFRESH_URL, json={"refresh_token": "fake-token-xyz"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotation_new_token_works(client: AsyncClient, captured_tokens: dict) -> None:
    tokens = await _signup_and_login(client, captured_tokens)
    rotate_resp = await client.post(REFRESH_URL, json={"refresh_token": tokens["refresh_token"]})
    new_refresh = rotate_resp.json()["refresh_token"]
    response = await client.post(REFRESH_URL, json={"refresh_token": new_refresh})
    assert response.status_code == 200


# ── logout ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logout_success(client: AsyncClient, captured_tokens: dict) -> None:
    tokens = await _signup_and_login(client, captured_tokens)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    response = await client.post(LOGOUT_URL, headers=headers)
    assert response.status_code == 204

    response = await client.post(REFRESH_URL, json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 401


# ── misc ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_multiple_users_independent(client: AsyncClient, captured_tokens: dict) -> None:
    user2 = {**VALID_USER, "email": "other@example.com"}
    t1 = await _signup_and_login(client, captured_tokens)
    t2 = await _signup_and_login(client, captured_tokens, user2)
    assert t1["access_token"] != t2["access_token"]
