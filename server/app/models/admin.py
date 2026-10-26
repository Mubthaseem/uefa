"""Admin Dashboard Request/Response Schemas (Spec 6.11 - 6.14)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


# =====================================================================
# Batches & Access Codes
# =====================================================================
class BatchCreateIn(BaseModel):
    """POST /v1/admin/codes/batches request body."""
    label: str | None = Field(None, max_length=255)
    count: int = Field(..., ge=1, le=1000, description="Batch size between 1 and 1000")
    expires_in_days: int | None = Field(None, ge=1, le=3650, description="Expiration in days (null for none)")


class BatchCreateOut(BaseModel):
    """POST /v1/admin/codes/batches response."""
    id: uuid.UUID
    count: int


class BatchListItem(BaseModel):
    """Entry in GET /v1/admin/codes/batches list."""
    id: uuid.UUID
    label: str | None
    count: int
    used: int
    exported: bool
    created_at: datetime
    expires_in_days: int | None


class CodeListItem(BaseModel):
    """Entry in GET /v1/admin/codes/batches/{id} (Plaintext is NEVER returned)."""
    id: uuid.UUID
    status: str
    created_at: datetime
    redeemed_at: datetime | None
    device_id: uuid.UUID | None


# =====================================================================
# Devices
# =====================================================================
class DeviceAdminItem(BaseModel):
    """Admin view of an enrolled device."""
    id: uuid.UUID
    install_id: uuid.UUID | None
    platform: str | None
    app_version: str | None
    note: str | None
    created_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None
    entitlement_status: str | None = None


class DeviceAdminDetail(DeviceAdminItem):
    """Detailed device inspection."""
    entitlements: list[dict[str, Any]] = []
    key_history: list[dict[str, Any]] = []
    token_count: int = 0


class DeviceUpdateIn(BaseModel):
    """PATCH /v1/admin/devices/{id}."""
    note: str | None = None


# =====================================================================
# Content Management (members_items)
# =====================================================================
class MemberItemCreateIn(BaseModel):
    """POST /v1/admin/members/items."""
    item_type: Literal["video", "audio", "text"]
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    media_ref: str = Field(
        ...,
        pattern=r"^(video|audio|text)/[a-zA-Z0-9_\-]+\.(mp4|webm|mp3|m4a|ogg|txt|md)$",
        description="Path relative to member-media bucket"
    )
    thumbnail_ref: str | None = None
    duration_seconds: int | None = Field(None, ge=1, le=86400)
    sort_order: int = 0
    published: bool = True
    min_app_version: str | None = Field(None, pattern=r"^\d+\.\d+\.\d+$")


class MemberItemUpdateIn(BaseModel):
    """PUT /v1/admin/members/items/{id}."""
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    media_ref: str | None = None
    thumbnail_ref: str | None = None
    duration_seconds: int | None = None
    sort_order: int | None = None
    published: bool | None = None
    min_app_version: str | None = None


class MemberItemAdminOut(BaseModel):
    """Full detail of members item in admin console."""
    id: uuid.UUID
    item_type: str
    title: str
    description: str | None
    media_ref: str
    thumbnail_ref: str | None
    duration_seconds: int | None
    sort_order: int
    published: bool
    min_app_version: str | None
    created_at: datetime
    updated_at: datetime


# =====================================================================
# Audit Log
# =====================================================================
class AuditLogItem(BaseModel):
    """Audit log entry."""
    id: int
    actor_id: uuid.UUID | None
    actor_email: str | None = None
    action: str
    target_type: str
    target_id: str | None
    metadata: dict[str, Any]
    created_at: datetime


# =====================================================================
# Admin Accounts
# =====================================================================
class AdminCreateIn(BaseModel):
    """POST /v1/admin/admins."""
    email: EmailStr
    password: str = Field(..., min_length=12)
    role: Literal["owner", "editor", "support"] = "support"


class AdminUpdateIn(BaseModel):
    """PATCH /v1/admin/admins/{id}."""
    role: Literal["owner", "editor", "support"] | None = None
    disabled: bool | None = None
    password: str | None = Field(None, min_length=12)


class AdminUserOut(BaseModel):
    """Admin user response."""
    id: uuid.UUID
    email: str
    role: str
    disabled: bool
    last_login_at: datetime | None
    created_at: datetime
    totp_setup_uri: str | None = None
