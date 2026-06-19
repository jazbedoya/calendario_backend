import asyncio
import secrets
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import AppException
from app.core.security import create_access_token, hash_password, verify_password
from app.modules.auth import repository as repo
from app.modules.auth.models import User
from app.modules.auth.schemas import GoogleAuthRequest, LoginRequest, PatchMeRequest, SignupRequest, TokenResponse, VerificationPendingResponse

_RESET_TOKEN_EXPIRE_SECONDS = 900  # 15 minutes
_VERIFICATION_TOKEN_EXPIRE_HOURS = 24
_RESEND_COOLDOWN_SECONDS = 60


def _create_reset_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc).timestamp() + _RESET_TOKEN_EXPIRE_SECONDS
    return jwt.encode(
        {"sub": user_id, "type": "reset", "exp": exp},
        settings.secret_key,
        algorithm="HS256",
    )


def _decode_reset_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        if payload.get("type") != "reset":
            raise AppException(400, "Invalid token")
        return str(payload["sub"])
    except (JWTError, KeyError):
        raise AppException(400, "Invalid or expired reset token")

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_LOGIN_SCOPES = ["openid", "email", "profile"]


def build_google_login_url(state: str, redirect_uri: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(_LOGIN_SCOPES),
        "access_type": "offline",
        "prompt": "select_account",
        "state": state,
    }
    return f"{_GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def google_login_via_code(db: AsyncSession, code: str, redirect_uri: str) -> TokenResponse:
    """Exchange authorization code → Google access_token → our JWT tokens."""
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if token_resp.status_code != 200:
        log.error("google.code_exchange_failed", status=token_resp.status_code)
        raise AppException(400, "Google authentication failed")
    google_access_token = token_resp.json().get("access_token")
    return await google_auth(db, GoogleAuthRequest(access_token=google_access_token))

log = structlog.get_logger()


async def signup(db: AsyncSession, data: SignupRequest, base_url: str) -> VerificationPendingResponse:
    existing = await repo.get_user_by_email(db, data.email)
    if existing:
        raise AppException(400, "Email already registered")

    hashed = hash_password(data.password)
    user = await repo.create_user(
        db,
        email=data.email,
        hashed_password=hashed,
        full_name=data.full_name,
        timezone=data.timezone,
    )

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=_VERIFICATION_TOKEN_EXPIRE_HOURS)
    await repo.set_verification_token(db, user, token, expires_at)

    verify_url = f"{base_url}/auth/verify?token={token}"
    if data.redirect_to:
        verify_url += f"&redirect_to={urllib.parse.quote(data.redirect_to)}"

    log.info("user.signup", user_id=str(user.id))

    if settings.resend_api_key:
        await _send_verification_email(user.email, user.full_name, verify_url)

    return VerificationPendingResponse(email=user.email)


async def login(db: AsyncSession, data: LoginRequest) -> TokenResponse:
    user = await repo.get_user_by_email(db, data.email)
    if not user or not verify_password(data.password, user.hashed_password):
        raise AppException(401, "Invalid credentials")
    if not user.email_verified:
        raise AppException(403, "email_not_verified")

    access_token = create_access_token(str(user.id))
    refresh_token = await repo.create_refresh_token(db, user.id)

    log.info("user.login", user_id=str(user.id))
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


async def refresh(db: AsyncSession, raw_token: str) -> TokenResponse:
    rt = await repo.get_refresh_token(db, raw_token)
    if not rt or rt.revoked:
        raise AppException(401, "Invalid or expired refresh token")

    expires_at = rt.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise AppException(401, "Invalid or expired refresh token")

    await repo.revoke_refresh_token(db, raw_token)
    new_access = create_access_token(str(rt.user_id))
    new_refresh = await repo.create_refresh_token(db, rt.user_id)

    log.info("token.refresh", user_id=str(rt.user_id))
    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


async def logout(db: AsyncSession, user_id: uuid.UUID) -> None:
    await repo.revoke_all_user_tokens(db, user_id)
    log.info("user.logout", user_id=str(user_id))


async def google_auth(db: AsyncSession, data: GoogleAuthRequest) -> TokenResponse:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {data.access_token}"},
        )
    if resp.status_code != 200:
        raise AppException(401, "Invalid Google token")

    payload = resp.json()
    google_id: str = payload.get("sub", "")
    email: str = payload.get("email", "")
    full_name: str = payload.get("name") or email.split("@")[0]

    if not google_id or not email:
        raise AppException(401, "Incomplete Google profile")

    user = await repo.get_user_by_google_id(db, google_id)
    if not user:
        user = await repo.get_user_by_email(db, email)
        if user:
            # Link google_id to existing email account
            user = await repo.update_user(db, user, google_id=google_id)
        else:
            user = await repo.create_google_user(db, email=email, full_name=full_name, google_id=google_id)

    access_token = create_access_token(str(user.id))
    refresh_token = await repo.create_refresh_token(db, user.id)

    log.info("user.google_auth", user_id=str(user.id))
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


async def update_me(db: AsyncSession, user: User, data: PatchMeRequest) -> User:
    updated = await repo.update_user(
        db,
        user,
        full_name=data.full_name,
        timezone=data.timezone,
        mascot_name=data.mascot_name,
        weekly_intentions=data.weekly_intentions,
        weekly_intentions_week=data.weekly_intentions_week,
        language=data.language,
    )
    log.info("user.update_me", user_id=str(user.id))
    return updated


async def request_password_reset(db: AsyncSession, email: str, base_url: str) -> None:
    user = await repo.get_user_by_email(db, email)
    if not user:
        return  # Don't reveal whether email exists
    token = _create_reset_token(str(user.id))
    redirect_url = f"{base_url}/auth/reset-password/redirect?token={token}"
    log.info("auth.password_reset_requested", user_id=str(user.id), redirect_url=redirect_url)
    if settings.resend_api_key:
        await _send_reset_email(user.email, user.full_name, redirect_url)


async def verify_email(db: AsyncSession, token: str) -> None:
    user = await repo.get_user_by_verification_token(db, token)
    if not user or not user.email_verification_expires_at:
        raise AppException(400, "Invalid or expired verification token")
    expires_at = user.email_verification_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise AppException(400, "Invalid or expired verification token")
    await repo.mark_email_verified(db, user)
    log.info("user.email_verified", user_id=str(user.id))


async def resend_verification(db: AsyncSession, email: str, base_url: str) -> None:
    user = await repo.get_user_by_email(db, email)
    if not user or user.email_verified:
        return  # Silent — don't reveal whether email exists or is already verified

    # Rate limit: reject if last email was sent less than 60s ago
    if user.email_verification_expires_at:
        expires_at = user.email_verification_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        sent_at = expires_at - timedelta(hours=_VERIFICATION_TOKEN_EXPIRE_HOURS)
        if datetime.now(timezone.utc) - sent_at < timedelta(seconds=_RESEND_COOLDOWN_SECONDS):
            raise AppException(429, "Please wait before requesting another email")

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=_VERIFICATION_TOKEN_EXPIRE_HOURS)
    await repo.set_verification_token(db, user, token, expires_at)

    verify_url = f"{base_url}/auth/verify?token={token}"
    if settings.resend_api_key:
        await _send_verification_email(user.email, user.full_name, verify_url)
    log.info("user.resend_verification", user_id=str(user.id))


async def _send_verification_email(to_email: str, full_name: str, verify_url: str) -> None:
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px 24px;background:#ffffff">
      <h1 style="color:#C8553D;font-size:22px;margin:0 0 16px">Avante</h1>
      <p style="color:#2D2D2D;font-size:16px;margin:0 0 8px">Hola {full_name},</p>
      <p style="color:#4A4A4A;margin:0 0 24px">Tu cuenta está casi lista. Solo tienes que verificar tu email para activarla.</p>
      <a href="{verify_url}" style="display:inline-block;background:#C8553D;color:#ffffff;text-decoration:none;padding:14px 28px;border-radius:12px;font-weight:700;font-size:15px">Iniciar sesión en la app</a>
      <p style="color:#9A9A9A;font-size:12px;margin:24px 0 4px">Si el botón no funciona, copia este enlace en tu navegador:</p>
      <p style="color:#9A9A9A;font-size:11px;word-break:break-all;margin:0 0 24px">{verify_url}</p>
      <hr style="border:none;border-top:1px solid #F0EDE8;margin:0 0 16px">
      <p style="color:#CCCCCC;font-size:11px;margin:0">Si no has creado una cuenta en Avante, ignora este mensaje. Este enlace expira en 24 horas.</p>
    </div>
    """
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.email_from,
                "to": [to_email],
                "subject": "Verifica tu cuenta · Avante",
                "html": html,
            },
        )


async def _send_reset_email(to_email: str, full_name: str, reset_url: str) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.email_from,
                "to": [to_email],
                "subject": "Recupera tu contraseña · Avante",
                "html": (
                    f"<p>Hola {full_name},</p>"
                    f"<p><a href='{reset_url}'>Pulsa aquí para restablecer tu contraseña</a></p>"
                    f"<p>El enlace expira en 15 minutos.</p>"
                ),
            },
        )


async def confirm_password_reset(db: AsyncSession, token: str, new_password: str) -> None:
    user_id_str = _decode_reset_token(token)
    try:
        uid = uuid.UUID(user_id_str)
    except ValueError:
        raise AppException(400, "Invalid token")
    user = await repo.get_user_by_id(db, uid)
    if not user:
        raise AppException(400, "User not found")
    await repo.update_user(db, user, hashed_password=hash_password(new_password))
    await repo.revoke_all_user_tokens(db, uid)
    log.info("auth.password_reset_confirmed", user_id=user_id_str)


async def get_user_by_id(db: AsyncSession, user_id: str) -> User:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise AppException(401, "Invalid token")
    user = await repo.get_user_by_id(db, uid)
    if not user:
        raise AppException(401, "User not found")
    return user
