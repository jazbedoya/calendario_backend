import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RecurrenceRule = Literal["daily", "weekly", "monthly"]


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    start_at: datetime
    end_at: datetime
    is_all_day: bool = False
    location: str | None = None
    layer: str = "work"
    recurrence_rule: RecurrenceRule | None = None


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    is_all_day: bool | None = None
    location: str | None = None
    layer: str | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    start_at: datetime
    end_at: datetime
    is_all_day: bool
    location: str | None
    layer: str
    source: str
    google_event_id: str | None
    recurrence_rule: str | None
    recurrence_parent_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
