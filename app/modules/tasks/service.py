import uuid
from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.tasks import repository as repo
from app.modules.tasks.models import DailyTask
from app.modules.tasks.schemas import CreateTaskRequest, PatchTaskRequest, StreakResponse

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


def _compute_streaks(done_dates: list[date], today: date) -> tuple[int, int]:
    """Pure function: returns (current_streak, longest_streak).

    The streak is maintained from previous days and TODAY counts as soon as
    at least one task is completed.  If today has no completions yet, we
    preserve the streak from yesterday so it isn't prematurely broken.
    """
    if not done_dates:
        return 0, 0

    date_set = set(done_dates)

    # Start from today; if nothing today yet, start from yesterday
    check = today if today in date_set else today - timedelta(days=1)
    current = 0
    while check in date_set:
        current += 1
        check -= timedelta(days=1)

    # Longest streak: scan sorted dates
    sorted_dates = sorted(date_set)
    longest = run = 1
    for i in range(1, len(sorted_dates)):
        if (sorted_dates[i] - sorted_dates[i - 1]).days == 1:
            run += 1
            longest = max(longest, run)
        else:
            run = 1

    return current, longest


async def get_streak(db: AsyncSession, user_id: uuid.UUID, timezone: str) -> StreakResponse:
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")

    from datetime import datetime
    today = datetime.now(tz).date()

    done_dates = await repo.get_done_dates(db, user_id)
    current, longest = _compute_streaks(done_dates, today)

    # Week Mon–Sun containing today
    date_set = set(done_dates)
    monday = today - timedelta(days=today.weekday())  # weekday(): Mon=0, Sun=6
    week_done = [monday + timedelta(days=i) in date_set for i in range(7)]

    return StreakResponse(current_streak=current, longest_streak=longest, week_done=week_done)
