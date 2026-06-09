import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.security import decode_access_token
from app.database import get_db
from app.modules.auth import repository as repo
from app.modules.auth.models import User

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = decode_access_token(credentials.credentials)
        user_id_str: str = payload["sub"]
        token_type: str = payload.get("type", "")
    except (JWTError, KeyError):
        raise AppException(401, "Invalid token")

    if token_type != "access":
        raise AppException(401, "Invalid token type")

    try:
        uid = uuid.UUID(user_id_str)
    except ValueError:
        raise AppException(401, "Invalid token")

    user = await repo.get_user_by_id(db, uid)
    if not user:
        raise AppException(401, "User not found")
    return user
