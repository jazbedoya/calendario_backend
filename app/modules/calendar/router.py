import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.calendar import service
from app.modules.calendar.schemas import CalendarEventOut, GoogleAccountStatus, SyncResult
from app.modules.calendar import repository as repo

router = APIRouter(prefix="/calendar", tags=["calendar"])


def _encode_state(user_id: uuid.UUID, redirect_to: str, callback_uri: str) -> str:
    exp = datetime.now(timezone.utc).timestamp() + 600  # 10 min
    return jwt.encode(
        {"sub": str(user_id), "exp": exp, "rto": redirect_to, "cbk": callback_uri, "type": "calendar"},
        settings.secret_key,
        algorithm="HS256",
    )


@router.get("/connect")
async def connect(
    redirect_to: str | None = Query(default=None),
    callback_uri: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Return the Google OAuth URL. redirect_to is where the app wants to land after auth."""
    default = f"{settings.deep_link_scheme}://calendar/connected"
    effective_callback = callback_uri or settings.google_callback_url
    state = _encode_state(current_user.id, redirect_to or default, effective_callback)
    url = service.build_oauth_url(state, effective_callback)
    return {"url": url}



@router.get("/status", response_model=GoogleAccountStatus)
async def status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GoogleAccountStatus:
    return await service.get_status(db, current_user.id)


@router.delete("/disconnect", status_code=204)
async def disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.disconnect_calendar(db, current_user.id)


@router.post("/sync", response_model=SyncResult)
async def sync(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SyncResult:
    count = await service.sync_user_calendar(db, current_user.id)
    return SyncResult(synced=count, message=f"Synced {count} events")


@router.get("/events", response_model=list[CalendarEventOut])
async def events(
    start: datetime = Query(default=None),
    end: datetime = Query(default=None),
    layer: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CalendarEventOut]:
    now = datetime.now(timezone.utc)
    start_at = start or now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_at = end or now.replace(day=28, hour=23, minute=59, second=59)
    rows = await repo.list_events(db, current_user.id, start_at, end_at, layer)
    return [CalendarEventOut.model_validate(r) for r in rows]
