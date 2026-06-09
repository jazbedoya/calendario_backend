from pydantic import BaseModel


class UpcomingEvent(BaseModel):
    id: str
    title: str
    start_at: str
    end_at: str
    layer: str
    is_all_day: bool


class WeekHours(BaseModel):
    family: float
    work: float
    personal: float


class HomeSummary(BaseModel):
    upcoming_events: list[UpcomingEvent]
    week_hours_by_layer: WeekHours
    today_tasks_pending: int
