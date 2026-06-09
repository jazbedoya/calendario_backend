import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import create_refresh_token_value, hash_token
from app.modules.auth.models import RefreshToken, User


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    email: str,
    hashed_password: str,
    full_name: str,
    timezone: str,
) -> User:
    user = User(email=email, hashed_password=hashed_password, full_name=full_name, timezone=timezone)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def create_refresh_token(db: AsyncSession, user_id: uuid.UUID) -> str:
    raw_token = create_refresh_token_value()
    token_hash = hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    rt = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(rt)
    await db.flush()
    return raw_token


async def get_refresh_token(db: AsyncSession, raw_token: str) -> RefreshToken | None:
    token_hash = hash_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    return result.scalar_one_or_none()


async def revoke_refresh_token(db: AsyncSession, raw_token: str) -> None:
    token_hash = hash_token(raw_token)
    await db.execute(
        update(RefreshToken).where(RefreshToken.token_hash == token_hash).values(revoked=True)
    )


async def revoke_all_user_tokens(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(RefreshToken).where(RefreshToken.user_id == user_id).values(revoked=True)
    )


async def get_user_by_google_id(db: AsyncSession, google_id: str) -> User | None:
    result = await db.execute(select(User).where(User.google_id == google_id))
    return result.scalar_one_or_none()


async def create_google_user(
    db: AsyncSession,
    email: str,
    full_name: str,
    google_id: str,
) -> User:
    import secrets
    unusable_hash = f"!google!{secrets.token_hex(32)}"
    user = User(email=email, hashed_password=unusable_hash, full_name=full_name, google_id=google_id)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def update_user(db: AsyncSession, user: User, **fields: object) -> User:
    for key, value in fields.items():
        if value is not None:
            setattr(user, key, value)
    await db.flush()
    await db.refresh(user)
    return user
