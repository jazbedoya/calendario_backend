from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> None:
    # TODO Sprint 1: validar JWT y retornar User
    raise NotImplementedError("Auth not implemented yet")
