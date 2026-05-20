from pydantic import PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_env: str = "development"
    secret_key: str
    debug: bool = False

    # Database
    database_url: PostgresDsn

    # Redis
    redis_url: RedisDsn

    # Auth
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    # Google OAuth (Sprint 2)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""

    # Fernet
    fernet_key: str = ""

    # Push (Sprint 5)
    expo_access_token: str = ""

    # Email (Sprint 5)
    resend_api_key: str = ""
    email_from: str = "noreply@example.com"

    @field_validator("secret_key")
    @classmethod
    def secret_key_min_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v


settings = Settings()
