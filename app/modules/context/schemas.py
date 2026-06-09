import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ContextEntryCreate(BaseModel):
    date: date
    energy_level: int = Field(ge=1, le=10)
    mood: int = Field(ge=1, le=10)
    notes: str | None = None
    event_id: uuid.UUID | None = None


class ContextEntryUpdate(BaseModel):
    energy_level: int | None = Field(default=None, ge=1, le=10)
    mood: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = None
    event_id: uuid.UUID | None = None


class ContextEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    event_id: uuid.UUID | None
    date: date
    energy_level: int
    mood: int
    notes: str | None
    created_at: datetime
    updated_at: datetime
