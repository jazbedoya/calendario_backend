import uuid

import structlog

from app.database import AsyncSessionLocal
from app.modules.calendar import service

log = structlog.get_logger()


async def sync_calendar_task(ctx: dict, user_id: str) -> dict[str, object]:
    """ARQ background task: sync Google Calendar events for a user."""
    uid = uuid.UUID(user_id)
    async with AsyncSessionLocal() as db:
        try:
            count = await service.sync_user_calendar(db, uid)
            await db.commit()
            log.info("task.calendar_sync.done", user_id=user_id, synced=count)
            return {"synced": count, "user_id": user_id}
        except Exception as exc:
            await db.rollback()
            log.error("task.calendar_sync.failed", user_id=user_id, error=str(exc))
            raise


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [sync_calendar_task]
    redis_settings = None  # Set at runtime from settings.redis_url
