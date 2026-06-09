import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import AppException
from app.database import get_db
from app.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.calendar import service
from app.modules.calendar.schemas import CalendarEventOut, GoogleAccountStatus, SyncResult
from app.modules.calendar import repository as repo

router = APIRouter(prefix="/calendar", tags=["calendar"])


def _encode_state(user_id: uuid.UUID, redirect_to: str) -> str:
    exp = datetime.now(timezone.utc).timestamp() + 600  # 10 min
    return jwt.encode(
        {"sub": str(user_id), "exp": exp, "rto": redirect_to},
        settings.secret_key,
        algorithm="HS256",
    )


def _decode_state(state: str) -> tuple[uuid.UUID, str]:
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=["HS256"])
        default = f"{settings.deep_link_scheme}://calendar/connected"
        return uuid.UUID(payload["sub"]), payload.get("rto", default)
    except (JWTError, KeyError, ValueError) as exc:
        raise AppException(400, "Invalid or expired OAuth state") from exc


@router.get("/connect")
async def connect(
    redirect_to: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Return the Google OAuth URL. redirect_to is where the app wants to land after auth."""
    default = f"{settings.deep_link_scheme}://calendar/connected"
    state = _encode_state(current_user.id, redirect_to or default)
    url = service.build_oauth_url(state)
    return {"url": url}


@router.get("/callback")
async def callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle Google OAuth callback. Redirects to the URL encoded in state."""
    import structlog
    log = structlog.get_logger()
    try:
        user_id, redirect_to = _decode_state(state)
        account = await service.connect_calendar(db, user_id, code)
        # Verificar que se otorgó el scope de calendar
        required = "https://www.googleapis.com/auth/calendar.readonly"
        if required not in (account.scopes or ""):
            await service.disconnect_calendar(db, user_id)
            error_url = redirect_to.replace("/connected", "/error").replace(
                f"{settings.deep_link_scheme}://calendar/connected",
                f"{settings.deep_link_scheme}://calendar/error",
            ) + "?reason=missing_calendar_scope"
            return RedirectResponse(url=error_url)
        return RedirectResponse(url=redirect_to)
    except Exception as exc:
        log.error("calendar.callback_error", error=str(exc))
        error_url = f"{settings.deep_link_scheme}://calendar/error"
        return RedirectResponse(url=error_url)


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
