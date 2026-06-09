import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GoogleAccountStatus(BaseModel):
    connected: bool
    google_email: str | None = None
    last_synced_at: datetime | None = None


class CalendarEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    google_event_id: str
    title: str
    description: str | None
    start_at: datetime
    end_at: datetime
    is_all_day: bool
    location: str | None
    layer: str


class SyncResult(BaseModel):
    synced: int
    message: str
