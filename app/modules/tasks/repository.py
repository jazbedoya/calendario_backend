import uuid
from datetime import date

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tasks.models import DailyTask


async def list_by_date(db: AsyncSession, user_id: uuid.UUID, task_date: date) -> list[DailyTask]:
    result = await db.execute(
        select(DailyTask)
        .where(DailyTask.user_id == user_id, DailyTask.date == task_date)
        .order_by(DailyTask.order, DailyTask.created_at)
    )
    return list(result.scalars().all())


async def create(
    db: AsyncSession, user_id: uuid.UUID, task_date: date, text: str, order: int = 0
) -> DailyTask:
    task = DailyTask(user_id=user_id, date=task_date, text=text, order=order)
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


async def get(db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID) -> DailyTask | None:
    result = await db.execute(
        select(DailyTask).where(DailyTask.id == task_id, DailyTask.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def update_task(
    db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID, **fields: object
) -> DailyTask | None:
    filtered = {k: v for k, v in fields.items() if v is not None}
    if not filtered:
        return await get(db, task_id, user_id)
    await db.execute(
        update(DailyTask)
        .where(DailyTask.id == task_id, DailyTask.user_id == user_id)
        .values(**filtered)
    )
    await db.flush()
    return await get(db, task_id, user_id)


async def delete_task(db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    result = await db.execute(
        delete(DailyTask).where(DailyTask.id == task_id, DailyTask.user_id == user_id)
    )
    await db.flush()
    return result.rowcount > 0
