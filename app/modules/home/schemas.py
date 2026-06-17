from pydantic import BaseModel


class UpcomingEvent(BaseModel):
    id: str
    title: str
    start_at: str
    end_at: str
    layer: str
    is_all_day: bool


class WeekEventCount(BaseModel):
    family: int
    work: int
    personal: int


class HomeSummary(BaseModel):
    upcoming_events: list[UpcomingEvent]
    week_events_by_layer: WeekEventCount
    today_tasks_pending: int
