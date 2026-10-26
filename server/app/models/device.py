"""Device Registration & Deletion Schemas (Spec 6.3 & 6.9)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EntitlementSummary(BaseModel):
    """Active entitlement information for a device."""
    model_config = ConfigDict(from_attributes=True)

    status: str = Field(..., description="active | revoked | expired")
    expires_at: datetime | None = Field(None, description="Expiration date or null for lifetime")


class DeviceRegisterIn(BaseModel):
    """POST /v1/devices/register request body."""
    install_id: uuid.UUID = Field(..., description="Client installation UUIDv4")
    platform: Literal["android", "ios"] = Field(..., description="Operating system platform")
    app_version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$", description="Semver app version (e.g. 1.0.0)")
    tz_offset_minutes: int | None = Field(
        default=0,
        ge=-720,
        le=840,
        description="Timezone offset in minutes from UTC (-720 to +840)"
    )


class DeviceRegisterOut(BaseModel):
    """POST /v1/devices/register response body."""
    device_id: uuid.UUID = Field(..., description="Internal backend device UUID")
    entitled: bool = Field(default=False, description="Whether device currently has active entitlement")
    entitlement: EntitlementSummary | None = Field(None, description="Entitlement details if entitled")


class DeviceDeleteIn(BaseModel):
    """POST /v1/devices/delete request body (GDPR)."""
    install_id: uuid.UUID = Field(..., description="Client installation UUID to be deleted")


class DeviceDeleteOut(BaseModel):
    """POST /v1/devices/delete response body."""
    deleted: bool = True
