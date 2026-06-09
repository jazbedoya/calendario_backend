import uuid
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.security import create_access_token, hash_password, verify_password
from app.modules.auth import repository as repo
from app.modules.auth.models import User
from app.modules.auth.schemas import GoogleAuthRequest, LoginRequest, PatchMeRequest, SignupRequest, TokenResponse

log = structlog.get_logger()


async def signup(db: AsyncSession, data: SignupRequest) -> TokenResponse:
    existing = await repo.get_user_by_email(db, data.email)
    if existing:
        raise AppException(400, "Email already registered")

    hashed = hash_password(data.password)
    user = await repo.create_user(
        db,
        email=data.email,
        hashed_password=hashed,
        full_name=data.full_name,
        timezone=data.timezone,
    )

    access_token = create_access_token(str(user.id))
    refresh_token = await repo.create_refresh_token(db, user.id)

    log.info("user.signup", user_id=str(user.id))
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


async def login(db: AsyncSession, data: LoginRequest) -> TokenResponse:
    user = await repo.get_user_by_email(db, data.email)
    if not user or not verify_password(data.password, user.hashed_password):
        raise AppException(401, "Invalid credentials")

    access_token = create_access_token(str(user.id))
    refresh_token = await repo.create_refresh_token(db, user.id)

    log.info("user.login", user_id=str(user.id))
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


async def refresh(db: AsyncSession, raw_token: str) -> TokenResponse:
    rt = await repo.get_refresh_token(db, raw_token)
    if not rt or rt.revoked:
        raise AppException(401, "Invalid or expired refresh token")

    expires_at = rt.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise AppException(401, "Invalid or expired refresh token")

    await repo.revoke_refresh_token(db, raw_token)
    new_access = create_access_token(str(rt.user_id))
    new_refresh = await repo.create_refresh_token(db, rt.user_id)

    log.info("token.refresh", user_id=str(rt.user_id))
    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


async def logout(db: AsyncSession, user_id: uuid.UUID) -> None:
    await repo.revoke_all_user_tokens(db, user_id)
    log.info("user.logout", user_id=str(user_id))


async def google_auth(db: AsyncSession, data: GoogleAuthRequest) -> TokenResponse:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {data.access_token}"},
        )
    if resp.status_code != 200:
        raise AppException(401, "Invalid Google token")

    payload = resp.json()
    google_id: str = payload.get("sub", "")
    email: str = payload.get("email", "")
    full_name: str = payload.get("name") or email.split("@")[0]

    if not google_id or not email:
        raise AppException(401, "Incomplete Google profile")

    user = await repo.get_user_by_google_id(db, google_id)
    if not user:
        user = await repo.get_user_by_email(db, email)
        if user:
            # Link google_id to existing email account
            user = await repo.update_user(db, user, google_id=google_id)
        else:
            user = await repo.create_google_user(db, email=email, full_name=full_name, google_id=google_id)

    access_token = create_access_token(str(user.id))
    refresh_token = await repo.create_refresh_token(db, user.id)

    log.info("user.google_auth", user_id=str(user.id))
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


async def update_me(db: AsyncSession, user: User, data: PatchMeRequest) -> User:
    updated = await repo.update_user(
        db,
        user,
        full_name=data.full_name,
        timezone=data.timezone,
        mascot_name=data.mascot_name,
        weekly_intentions=data.weekly_intentions,
        weekly_intentions_week=data.weekly_intentions_week,
        language=data.language,
    )
    log.info("user.update_me", user_id=str(user.id))
    return updated


async def get_user_by_id(db: AsyncSession, user_id: str) -> User:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise AppException(401, "Invalid token")
    user = await repo.get_user_by_id(db, uid)
    if not user:
        raise AppException(401, "User not found")
    return user
