"""Runtime Configuration Schemas (Spec 6.6)."""

from typing import Any

from pydantic import BaseModel, Field


class AppBranding(BaseModel):
    """Client brand display tokens."""
    name: str = "DayJournal"
    tagline: str = "Your private daily journal"
    primary_color: str = "#4F6DF5"


class MemberLabels(BaseModel):
    """Dynamic client strings for members unlock UI."""
    redeem_field: str = "Access code"
    redeem_button: str = "Unlock"
    success: str = "Members area unlocked."
    error: str = "That code is not valid."


class MembersConfig(BaseModel):
    """Dynamic members section configuration."""
    enabled: bool = True
    tab_label: str = "Members"
    locked_title: str = "Members area"
    locked_body: str = "Enter an access code to unlock."
    labels: MemberLabels = Field(default_factory=MemberLabels)
    base_url: str | None = None


class MaintenanceConfig(BaseModel):
    """Maintenance window alert details."""
    active: bool = False
    message: str | None = None


class ConfigOut(BaseModel):
    """Complete runtime configuration contract for client app (Spec 6.6)."""
    config_version: int = Field(default=1, description="Version sequence counter")
    app: AppBranding = Field(default_factory=AppBranding)
    flags: dict[str, Any] = Field(default_factory=dict)
    min_app_version: str = "1.0.0"
    maintenance: MaintenanceConfig | None = None
    members: MembersConfig = Field(default_factory=MembersConfig)
