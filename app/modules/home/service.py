import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.home import repository as repo
from app.modules.home.schemas import HomeSummary

log = structlog.get_logger()


async def get_summary(db: AsyncSession, user_id: uuid.UUID) -> HomeSummary:
    summary = await repo.get_home_summary(db, user_id)
    log.info("home.summary", user_id=str(user_id), upcoming=len(summary.upcoming_events))
    return summary
