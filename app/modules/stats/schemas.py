from pydantic import BaseModel


class LayerStat(BaseModel):
    layer: str
    count: int
    total_hours: float


class BusyDay(BaseModel):
    date: str   # "yyyy-MM-dd"
    count: int


class MonthlyStats(BaseModel):
    year: int
    month: int
    total_events: int
    by_layer: list[LayerStat]
    busiest_days: list[BusyDay]  # top 5 ordered by count desc
