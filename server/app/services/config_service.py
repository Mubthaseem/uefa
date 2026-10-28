"""Runtime Configuration and Feature Flags Service (Spec 5.8, 6.6, 6.13)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.config_api import AppBranding, ConfigOut, MemberLabels, MembersConfig
from app.models.db_models import AppConfig, FeatureFlag

settings = get_settings()

DEFAULT_CONFIG = {
    "brand.app_name": "DayJournal",
    "brand.tagline": "Your private daily journal",
    "brand.primary_color": "#4F6DF5",
    "members.enabled": True,
    "members.tab_label": "Members",
    "members.locked_title": "Members area",
    "members.locked_body": "Enter an access code to unlock.",
    "members.redeem_field_label": "Access code",
    "members.redeem_button_label": "Unlock",
    "members.redeem_success_message": "Members area unlocked.",
    "members.redeem_error_message": "That code is not valid.",
    "journal.export_pdf": True,
    "journal.export_text": True,
    "journal.reminders": False,
    "system.config_version": 1
}

DEFAULT_FLAGS = {
    "members.enabled": True,
    "journal.export_pdf": True,
    "journal.export_text": True,
    "journal.reminders": False,
    "zeta.streaming.enabled": False,
    "zeta.streaming.min_app_version": "1.0.0",
}


async def seed_defaults_if_empty(db: AsyncSession) -> None:
    """Ensure essential configuration rows exist."""
    res = await db.execute(select(AppConfig).limit(1))
    if not res.scalars().first():
        for k, v in DEFAULT_CONFIG.items():
            db.add(AppConfig(key=k, value=v))
        for k, v in DEFAULT_FLAGS.items():
            db.add(FeatureFlag(key=k, value=v))
        await db.commit()


async def get_config_version(db: AsyncSession) -> int:
    """Get active config version integer."""
    stmt = select(AppConfig).where(AppConfig.key == "system.config_version")
    res = await db.execute(stmt)
    row = res.scalars().first()
    if row and isinstance(row.value, int):
        return row.value
    return settings.CONFIG_VERSION


async def bump_config_version(db: AsyncSession, admin_id: uuid.UUID | None = None) -> int:
    """Increment config version counter to invalidate client ETags."""
    stmt = select(AppConfig).where(AppConfig.key == "system.config_version")
    res = await db.execute(stmt)
    row = res.scalars().first()
    new_version = (row.value + 1) if (row and isinstance(row.value, int)) else 2
    if row:
        row.value = new_version
        row.updated_by = admin_id
    else:
        db.add(AppConfig(key="system.config_version", value=new_version, updated_by=admin_id))
    await db.flush()
    return new_version


async def assemble_runtime_config(db: AsyncSession) -> ConfigOut:
    """
    Assemble the runtime config payload matching Spec Section 6.6.
    """
    # Fetch all app_config
    cfg_rows = (await db.execute(select(AppConfig))).scalars().all()
    cfg_map = {row.key: row.value for row in cfg_rows}

    # Fetch all flags
    flag_rows = (await db.execute(select(FeatureFlag))).scalars().all()
    flags_map = {row.key: row.value for row in flag_rows}
    if not flags_map:
        flags_map = DEFAULT_FLAGS.copy()
    else:
        for k, v in DEFAULT_FLAGS.items():
            if k not in flags_map:
                flags_map[k] = v

    # Fill default config if missing
    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg_map:
            cfg_map[k] = v

    version = cfg_map.get("system.config_version", 1)

    app_branding = AppBranding(
        name=str(cfg_map.get("brand.app_name", "DayJournal")),
        tagline=str(cfg_map.get("brand.tagline", "Your private daily journal")),
        primary_color=str(cfg_map.get("brand.primary_color", "#4F6DF5"))
    )

    labels = MemberLabels(
        redeem_field=str(cfg_map.get("members.redeem_field_label", "Access code")),
        redeem_button=str(cfg_map.get("members.redeem_button_label", "Unlock")),
        success=str(cfg_map.get("members.redeem_success_message", "Members area unlocked.")),
        error=str(cfg_map.get("members.redeem_error_message", "That code is not valid."))
    )

    members_cfg = MembersConfig(
        enabled=bool(cfg_map.get("members.enabled", True)),
        tab_label=str(cfg_map.get("members.tab_label", "Members")),
        locked_title=str(cfg_map.get("members.locked_title", "Members area")),
        locked_body=str(cfg_map.get("members.locked_body", "Enter an access code to unlock.")),
        labels=labels,
        base_url=f"{settings.API_HOST.rstrip('/')}/v1/members"
    )

    return ConfigOut(
        config_version=int(version),
        app=app_branding,
        flags=flags_map,
        min_app_version="1.0.0",
        maintenance=None,
        members=members_cfg
    )
