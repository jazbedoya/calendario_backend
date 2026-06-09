import uuid
from datetime import date

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.tasks import repository as repo
from app.modules.tasks.models import DailyTask
from app.modules.tasks.schemas import CreateTaskRequest, PatchTaskRequest

log = structlog.get_logger()


async def list_today(db: AsyncSession, user_id: uuid.UUID, task_date: date) -> list[DailyTask]:
    return await repo.list_by_date(db, user_id, task_date)


async def create(db: AsyncSession, user_id: uuid.UUID, data: CreateTaskRequest) -> DailyTask:
    existing = await repo.list_by_date(db, user_id, data.date)
    order = len(existing)
    task = await repo.create(db, user_id, data.date, data.text.strip(), order)
    log.info("task.created", user_id=str(user_id), task_id=str(task.id))
    return task


async def patch(
    db: AsyncSession, user_id: uuid.UUID, task_id: uuid.UUID, data: PatchTaskRequest
) -> DailyTask:
    task = await repo.get(db, task_id, user_id)
    if not task:
        raise AppException(404, "Task not found")
    fields = data.model_dump(exclude_unset=True)
    if "text" in fields:
        fields["text"] = fields["text"].strip()
    # update_task filters out None values, but `done=False` must pass through
    await repo.update_task(db, task_id, user_id, **fields)
    updated = await repo.get(db, task_id, user_id)
    return updated  # type: ignore[return-value]


async def delete(db: AsyncSession, user_id: uuid.UUID, task_id: uuid.UUID) -> None:
    deleted = await repo.delete_task(db, task_id, user_id)
    if not deleted:
        raise AppException(404, "Task not found")
    log.info("task.deleted", user_id=str(user_id), task_id=str(task_id))
