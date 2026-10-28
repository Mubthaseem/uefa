"""Application Configuration using pydantic-settings."""

import base64
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Complete environment configuration for DayJournal backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Core Environment
    ENVIRONMENT: str = Field(default="staging", description="staging | production | test")
    API_HOST: str = Field(default="https://api.dayjournal.app", description="Public API hostname")
    CONFIG_VERSION: int = Field(default=1, description="Config version integer for ETag tracking")

    # Database & Redis
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
        description="Async PostgreSQL connection string"
    )
    REDIS_URL: str = Field(
        default="redis://localhost:6379",
        description="Upstash or local Redis connection URL"
    )

    # JWT Authentication (EdDSA / Ed25519)
    JWT_PRIVATE_KEY: str = Field(default="", description="Ed25519 Private Key in PEM format")
    JWT_PUBLIC_KEY: str = Field(default="", description="Ed25519 Public Key in PEM format")
    JWT_KID: str = Field(default="k1", description="Key ID for JWT header")
    ACCESS_TOKEN_EXPIRE_SECONDS: int = Field(default=2592000, description="Access token lifetime (30 days)")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=30, description="Refresh token lifetime (30 days)")
    ADMIN_TOKEN_EXPIRE_SECONDS: int = Field(default=1800, description="Admin token lifetime (30 mins)")
    MFA_PENDING_EXPIRE_SECONDS: int = Field(default=60, description="MFA pending token lifetime (60 secs)")

    # Cryptographic Secrets (Base64)
    HMAC_PEPPER: str = Field(
        default="dGVzdF9wZXBwZXJfNjRfYnl0ZXNfbG9uZ19zdHJpbmdfZXhhbXBsZV9mb3JfdjJfYmFja2VuZF9zZWNyZXQ=",
        description="Base64 encoded 64-byte secret for HMAC-SHA256 Crockford codes"
    )
    ADMIN_SESSION_SECRET: str = Field(
        default="YWRtaW5fc2Vzc2lvbl9zZWNyZXRfMzJfYnl0ZXNfZXhhbXBsZQ==",
        description="Base64 encoded 32-byte secret for admin session cookies"
    )
    TOTP_ENCRYPTION_KEY: str = Field(
        default="dGVzdF8zMl9ieXRlc19rZXlfMTIzNDU2Nzg5MDEyMzQ1Ng==",
        description="Base64 encoded 32-byte AES-256-GCM key for TOTP secret & code export"
    )
    SIGNED_URL_SECRET: str = Field(
        default="c2lnbmVkX3VybF9zZWNyZXRfMzJfYnl0ZXNfbG9uZ19leGFtcGxl",
        description="Base64 encoded 32-byte secret for HMAC signed URLs"
    )

    # Supabase Storage & Service Role
    SUPABASE_URL: str = Field(default="https://xyzcompany.supabase.co", description="Supabase project URL")
    SUPABASE_SERVICE_ROLE_KEY: str = Field(default="", description="Supabase service role JWT")
    STORAGE_BUCKET: str = Field(default="member-media", description="Private storage bucket for VIP media")

    # Dynamic Streaming Portal GitHub Loader
    PORTAL_GITHUB_RAW_URL: str = Field(
        default="https://raw.githubusercontent.com/Mubthaseem/uefa/main/server/app/templates/streaming_portal.html",
        description="GitHub raw URL for streaming portal HTML template"
    )

    # CORS
    CORS_ORIGINS: str = Field(
        default="https://panel.dayjournal.app,http://localhost:3000,http://127.0.0.1:3000",
        description="Comma-separated origins for CORS"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def hmac_pepper_bytes(self) -> bytes:
        try:
            return base64.b64decode(self.HMAC_PEPPER)
        except Exception:
            return self.HMAC_PEPPER.encode("utf-8")

    @property
    def totp_encryption_key_bytes(self) -> bytes:
        try:
            raw = base64.b64decode(self.TOTP_ENCRYPTION_KEY)
            if len(raw) == 32:
                return raw
            # Pad or truncate to 32 bytes for AES-256
            return (raw * 2)[:32]
        except Exception:
            return (self.TOTP_ENCRYPTION_KEY.encode("utf-8") * 2)[:32]

    @property
    def signed_url_secret_bytes(self) -> bytes:
        try:
            return base64.b64decode(self.SIGNED_URL_SECRET)
        except Exception:
            return self.SIGNED_URL_SECRET.encode("utf-8")


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
