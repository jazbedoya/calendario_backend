import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from cryptography.fernet import Fernet

from app.config import settings
from app.core.exceptions import AppException
from app.modules.calendar import repository as repo
from app.modules.calendar.models import GoogleCalendarAccount
from app.modules.calendar.schemas import GoogleAccountStatus

log = structlog.get_logger()

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
_SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def _get_fernet() -> Fernet:
    if not settings.fernet_key:
        raise AppException(503, "Google Calendar not configured: missing FERNET_KEY")
    return Fernet(settings.fernet_key.encode())


def _require_google_config() -> None:
    if not settings.google_client_id or not settings.google_client_secret:
        raise AppException(503, "Google Calendar not configured")


def _encrypt(fernet: Fernet, value: str) -> str:
    return fernet.encrypt(value.encode()).decode()


def _decrypt(fernet: Fernet, value: str) -> str:
    return fernet.decrypt(value.encode()).decode()


def build_oauth_url(state: str, redirect_uri: str) -> str:
    _require_google_config()
    import urllib.parse

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{_GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code(code: str, redirect_uri: str) -> dict[str, str]:
    _require_google_config()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code != 200:
        raise AppException(400, f"Google token exchange failed: {resp.text}")
    return resp.json()  # type: ignore[no-any-return]


def decode_id_token(id_token: str) -> tuple[str, str]:
    """Decode JWT payload (no verification) to extract sub and email."""
    try:
        payload_b64 = id_token.split(".")[1]
        # Add padding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload["sub"], payload["email"]
    except Exception as exc:
        raise AppException(400, "Failed to decode Google id_token") from exc


async def connect_calendar(
    db: object,
    user_id: uuid.UUID,
    code: str,
    redirect_uri: str,
) -> GoogleCalendarAccount:
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(db, AsyncSession)
    fernet = _get_fernet()
    token_data = await exchange_code(code, redirect_uri)

    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token", "")
    expires_in = int(token_data.get("expires_in", 3600))
    id_token = token_data.get("id_token", "")
    scopes = token_data.get("scope", "")

    google_account_id, google_email = decode_id_token(id_token) if id_token else ("", "")
    token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    account = await repo.save_google_account(
        db,
        user_id=user_id,
        google_account_id=google_account_id,
        google_email=google_email,
        access_token_enc=_encrypt(fernet, access_token),
        refresh_token_enc=_encrypt(fernet, refresh_token),
        token_expiry=token_expiry,
        scopes=scopes,
    )
    log.info("calendar.connected", user_id=str(user_id), google_email=google_email)
    return account


async def disconnect_calendar(db: object, user_id: uuid.UUID) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(db, AsyncSession)
    await repo.delete_google_account(db, user_id)
    await repo.delete_events_for_user(db, user_id)
    log.info("calendar.disconnected", user_id=str(user_id))


async def get_status(db: object, user_id: uuid.UUID) -> GoogleAccountStatus:
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(db, AsyncSession)
    account = await repo.get_google_account(db, user_id)
    if not account:
        return GoogleAccountStatus(connected=False)
    return GoogleAccountStatus(
        connected=True,
        google_email=account.google_email,
        last_synced_at=account.last_synced_at,
    )


async def _refresh_access_token(
    db: object, user_id: uuid.UUID, account: GoogleCalendarAccount
) -> str:
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(db, AsyncSession)
    _require_google_config()
    fernet = _get_fernet()
    refresh_token = _decrypt(fernet, account.refresh_token_enc)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            },
        )
    if resp.status_code != 200:
        raise AppException(401, "Google token refresh failed — reconnect required")

    data = resp.json()
    new_access = data["access_token"]
    expires_in = int(data.get("expires_in", 3600))
    token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    new_refresh = data.get("refresh_token", refresh_token)

    await repo.update_google_account_tokens(
        db,
        user_id=user_id,
        access_token_enc=_encrypt(fernet, new_access),
        refresh_token_enc=_encrypt(fernet, new_refresh),
        token_expiry=token_expiry,
    )
    return new_access


async def sync_user_calendar(db: object, user_id: uuid.UUID) -> int:
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(db, AsyncSession)
    account = await repo.get_google_account(db, user_id)
    if not account:
        raise AppException(400, "Google Calendar not connected")

    fernet = _get_fernet()

    # Refresh token if expired
    now = datetime.now(timezone.utc)
    if account.token_expiry and account.token_expiry.replace(tzinfo=timezone.utc) < now:
        access_token = await _refresh_access_token(db, user_id, account)
    else:
        access_token = _decrypt(fernet, account.access_token_enc)

    time_min = (now - timedelta(days=30)).isoformat()
    time_max = (now + timedelta(days=90)).isoformat()

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _GOOGLE_CALENDAR_URL.format(calendar_id="primary"),
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "maxResults": "250",
                "orderBy": "startTime",
            },
        )
    log.info("calendar.api_response", status=resp.status_code, user_id=str(user_id))
    if resp.status_code != 200:
        log.error("calendar.api_error", status=resp.status_code, body=resp.text[:500], user_id=str(user_id))
        raise AppException(502, f"Google Calendar API error: {resp.status_code}")

    items = resp.json().get("items", [])
    log.info("calendar.items_fetched", count=len(items), user_id=str(user_id))

    rows: list[dict] = []
    for item in items:
        if item.get("status") == "cancelled":
            continue

        start_raw = item.get("start", {})
        end_raw = item.get("end", {})
        is_all_day = "date" in start_raw and "dateTime" not in start_raw

        if is_all_day:
            start_at = datetime.fromisoformat(start_raw["date"]).replace(tzinfo=timezone.utc)
            end_at = datetime.fromisoformat(end_raw["date"]).replace(tzinfo=timezone.utc)
        else:
            start_at = datetime.fromisoformat(start_raw["dateTime"])
            end_at = datetime.fromisoformat(end_raw["dateTime"])
            if start_at.tzinfo is None:
                start_at = start_at.replace(tzinfo=timezone.utc)
            if end_at.tzinfo is None:
                end_at = end_at.replace(tzinfo=timezone.utc)

        rows.append({
            "user_id": user_id,
            "google_event_id": item["id"],
            "calendar_id": "primary",
            "title": item.get("summary", ""),
            "description": item.get("description"),
            "start_at": start_at,
            "end_at": end_at,
            "is_all_day": is_all_day,
            "location": item.get("location"),
        })

    count = await repo.upsert_events_batch(db, rows)
    await repo.update_last_synced(db, user_id)
    log.info("calendar.synced", user_id=str(user_id), count=count)
    return count
