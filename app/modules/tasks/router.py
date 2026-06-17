import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.tasks import service
from app.modules.tasks.schemas import CreateTaskRequest, PatchTaskRequest, StreakResponse, TaskResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/daily", response_model=list[TaskResponse])
async def list_daily(
    date: date = Query(..., description="Date in yyyy-MM-dd (user's local timezone)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TaskResponse]:
    tasks = await service.list_today(db, current_user.id, date)
    return [TaskResponse.model_validate(t) for t in tasks]


@router.post("/daily", response_model=TaskResponse, status_code=201)
async def create_task(
    data: CreateTaskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    task = await service.create(db, current_user.id, data)
    return TaskResponse.model_validate(task)


@router.patch("/daily/{task_id}", response_model=TaskResponse)
async def patch_task(
    task_id: uuid.UUID,
    data: PatchTaskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    task = await service.patch(db, current_user.id, task_id, data)
    return TaskResponse.model_validate(task)


@router.get("/streak", response_model=StreakResponse)
async def get_streak(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreakResponse:
    return await service.get_streak(db, current_user.id, current_user.timezone)


@router.delete("/daily/{task_id}", status_code=204)
async def delete_task(
    task_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.delete(db, current_user.id, task_id)
