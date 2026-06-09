from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.home import service
from app.modules.home.schemas import HomeSummary

router = APIRouter(prefix="/home", tags=["home"])


@router.get("/summary", response_model=HomeSummary)
async def get_home_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HomeSummary:
    return await service.get_summary(db, current_user.id)
