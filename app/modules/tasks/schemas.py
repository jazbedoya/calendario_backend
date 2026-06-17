import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class CreateTaskRequest(BaseModel):
    date: date
    text: str = Field(min_length=1, max_length=200)


class PatchTaskRequest(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=200)
    done: bool | None = None


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    date: date
    text: str
    done: bool
    order: int
    created_at: datetime


class StreakResponse(BaseModel):
    current_streak: int
    longest_streak: int
    week_done: list[bool]  # 7 booleans, index 0 = Monday of current week
