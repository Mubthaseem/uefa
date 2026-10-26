"""Authentication and Token Schemas (Spec 6.5 & 6.10)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# Client Refresh
class RefreshIn(BaseModel):
    """POST /v1/auth/refresh request body."""
    refresh_token: str = Field(..., description="Opaque refresh token")
    install_id: uuid.UUID = Field(..., description="Device installation UUIDv4")


class TokenPairOut(BaseModel):
    """POST /v1/auth/refresh response body."""
    access_token: str = Field(..., description="EdDSA signed JWT access token")
    expires_in: int = Field(default=900, description="Lifetime in seconds")
    token_type: str = Field(default="bearer", description="Token type")
    refresh_token: str = Field(..., description="Newly rotated opaque refresh token")


# Admin Auth
class AdminLoginIn(BaseModel):
    """POST /v1/admin/login request body."""
    email: EmailStr = Field(..., description="Admin email address")
    password: str = Field(..., min_length=8, description="Admin password")


class AdminLoginOut(BaseModel):
    """POST /v1/admin/login response body."""
    mfa_required: bool = True
    pending_token: str = Field(..., description="Single-use short-lived JWT for MFA step")


class AdminMfaVerifyIn(BaseModel):
    """POST /v1/admin/mfa/verify request body."""
    pending_token: str = Field(..., description="Pending token from login step")
    totp: str = Field(..., min_length=6, max_length=6, description="6-digit TOTP code")


class AdminInfo(BaseModel):
    """Admin user profile summary."""
    id: uuid.UUID
    email: str
    role: str
    last_login_at: datetime | None = None


class AdminAuthOut(BaseModel):
    """POST /v1/admin/mfa/verify response body."""
    access_token: str = Field(..., description="Admin JWT (aud: admin)")
    admin: AdminInfo
