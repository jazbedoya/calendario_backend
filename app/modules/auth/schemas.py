import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel, EmailStr


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    timezone: str = "UTC"
    redirect_to: str | None = None  # Deep link para abrir la app tras verificar


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    timezone: str
    mascot_name: str
    weekly_intentions: Any | None = None
    weekly_intentions_week: date | None = None
    language: str = "es"

    model_config = {"from_attributes": True}


class PatchMeRequest(BaseModel):
    full_name: str | None = None
    timezone: str | None = None
    mascot_name: str | None = None
    weekly_intentions: Any | None = None
    weekly_intentions_week: date | None = None
    language: str | None = None


class GoogleAuthRequest(BaseModel):
    access_token: str


class VerificationPendingResponse(BaseModel):
    detail: str = "verification_email_sent"
    email: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
