import base64
import json as _json
import urllib.parse
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.core.rate_limit import limiter
from app.dependencies import get_current_user
from app.modules.auth import service
from app.modules.auth.models import User
from app.modules.auth.schemas import ForgotPasswordRequest, GoogleAuthRequest, LoginRequest, PatchMeRequest, ResendVerificationRequest, ResetPasswordRequest, SignupRequest, TokenResponse, UserResponse, VerificationPendingResponse

log = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])


class RefreshRequest(BaseModel):
    refresh_token: str


def _encode_login_state(redirect_to: str, callback_uri: str) -> str:
    exp = datetime.now(timezone.utc).timestamp() + 600
    return jwt.encode(
        {"rto": redirect_to, "cbk": callback_uri, "exp": exp, "type": "login"},
        settings.secret_key,
        algorithm="HS256",
    )


def _decode_state_payload(state: str) -> dict:  # type: ignore[type-arg]
    """Decode OAuth state — accepts signed JWT or unsigned base64 JSON.
    Returns payload dict or safe fallback."""
    try:
        return jwt.decode(state, settings.secret_key, algorithms=["HS256"])
    except (JWTError, KeyError):
        pass
    try:
        padded = state + "=" * (-len(state) % 4)
        return _json.loads(base64.b64decode(padded).decode())
    except Exception:
        pass
    return {"rto": f"{settings.deep_link_scheme}://google-login-callback", "type": "login"}



@router.get("/google/connect")
async def google_connect(
    redirect_to: str = Query(...),
    callback_uri: str | None = Query(default=None),
) -> dict[str, str]:
    """Returns the Google OAuth URL for mobile login. No auth required."""
    effective_callback = callback_uri or settings.google_callback_url
    state = _encode_login_state(redirect_to, effective_callback)
    return {"url": service.build_google_login_url(state, effective_callback)}


@router.get("/google/callback")
async def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Unified Google OAuth callback for login and calendar connect."""
    payload = _decode_state_payload(state or "")
    flow_type = payload.get("type", "login")
    redirect_to = str(payload.get("rto", f"{settings.deep_link_scheme}://google-login-callback"))

    if error or not code:
        return RedirectResponse(url=f"{redirect_to}?error={urllib.parse.quote(error or 'cancelled')}")

    callback_uri = str(payload.get("cbk", settings.google_callback_url))
    try:
        if flow_type == "calendar":
            from app.modules.calendar import service as cal_service
            user_id = uuid.UUID(str(payload["sub"]))
            account = await cal_service.connect_calendar(db, user_id, code, redirect_uri=callback_uri)
            required = "https://www.googleapis.com/auth/calendar.readonly"
            if required not in (account.scopes or ""):
                await cal_service.disconnect_calendar(db, user_id)
                await db.commit()
                return RedirectResponse(url=f"{redirect_to}?error=missing_calendar_scope")
            await db.commit()
            return RedirectResponse(url=redirect_to)
        else:
            tokens = await service.google_login_via_code(db, code, redirect_uri=callback_uri)
            await db.commit()
            params = urllib.parse.urlencode({
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
            })
            return RedirectResponse(url=f"{redirect_to}?{params}")
    except Exception as exc:
        log.error("auth.google_callback", flow=flow_type, error=str(exc))
        return RedirectResponse(url=f"{redirect_to}?error=server_error")


@router.post("/google", response_model=TokenResponse)
async def google_auth(data: GoogleAuthRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await service.google_auth(db, data)
    await db.commit()
    return result


@router.post("/signup", response_model=VerificationPendingResponse, status_code=202)
@limiter.limit("3/minute")
async def signup(data: SignupRequest, request: Request, db: AsyncSession = Depends(get_db)) -> VerificationPendingResponse:
    base_url = settings.app_base_url or str(request.base_url).rstrip("/")
    return await service.signup(db, data, base_url)


@router.get("/verify", response_model=None)
async def verify_email(
    token: str = Query(...),
    redirect_to: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse | HTMLResponse:
    try:
        await service.verify_email(db, token)
        if redirect_to:
            return RedirectResponse(url=redirect_to)
        html = """<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Cuenta verificada · Avante</title>
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:sans-serif;text-align:center;padding:60px 24px;background:#FAF9F7;margin:0">
  <p style="font-size:48px;margin:0 0 16px">🐢</p>
  <h1 style="color:#C8553D;font-size:26px;margin:0 0 12px">¡Cuenta verificada!</h1>
  <p style="color:#4A4A4A;font-size:16px;max-width:320px;margin:0 auto">
    Ya puedes iniciar sesión en la app Avante con tu email y contraseña.
  </p>
</body></html>"""
    except Exception:
        html = """<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Enlace inválido · Avante</title>
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:sans-serif;text-align:center;padding:60px 24px;background:#FAF9F7;margin:0">
  <p style="font-size:48px;margin:0 0 16px">⚠️</p>
  <h1 style="color:#2D2D2D;font-size:24px;margin:0 0 12px">Enlace inválido o expirado</h1>
  <p style="color:#4A4A4A;font-size:15px;max-width:320px;margin:0 auto">
    Solicita un nuevo enlace de verificación desde la app.
  </p>
</body></html>"""
    return HTMLResponse(content=html)


@router.post("/resend-verification", status_code=204)
@limiter.limit("2/minute")
async def resend_verification(data: ResendVerificationRequest, request: Request, db: AsyncSession = Depends(get_db)) -> None:
    base_url = settings.app_base_url or str(request.base_url).rstrip("/")
    await service.resend_verification(db, data.email, base_url)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    return await service.login(db, data)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    return await service.refresh(db, data.refresh_token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse)
async def patch_me(
    data: PatchMeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    updated = await service.update_me(db, current_user, data)
    await db.commit()
    return UserResponse.model_validate(updated)


@router.post("/forgot-password", status_code=204)
@limiter.limit("2/minute")
async def forgot_password(
    data: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    base_url = str(request.base_url).rstrip("/")
    await service.request_password_reset(db, data.email, base_url)


@router.post("/reset-password", status_code=204)
@limiter.limit("3/minute")
async def reset_password(
    data: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.confirm_password_reset(db, data.token, data.new_password)
    await db.commit()


@router.get("/reset-password/redirect")
async def reset_password_redirect(token: str = Query(...)) -> RedirectResponse:
    return RedirectResponse(url=f"{settings.deep_link_scheme}://reset-password?token={token}")


@router.post("/logout", status_code=204)
async def logout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.logout(db, current_user.id)
