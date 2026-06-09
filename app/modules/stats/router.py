import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from . import service
from .schemas import MonthlyStats

router = APIRouter(prefix="/stats", tags=["stats"])

_today = datetime.date.today


@router.get("/monthly", response_model=MonthlyStats)
async def monthly_stats(
    year: int = Query(default=None),
    month: int = Query(default=None, ge=1, le=12),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MonthlyStats:
    today = datetime.date.today()
    return await service.get_monthly_stats(
        db,
        current_user.id,
        year if year is not None else today.year,
        month if month is not None else today.month,
    )
