"""Admin Dynamic Configuration and Remote Flags Management (Spec 6.13)."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_admin
from app.models.db_models import Admin, AppConfig, FeatureFlag
from app.services.audit_service import log_audit_event
from app.services.config_service import bump_config_version

router = APIRouter(prefix="/v1/admin", tags=["Admin Config"])


@router.get("/config")
async def get_all_config(
    admin: Admin = Depends(require_admin(["owner", "editor", "support"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all active app_config key/value entries (Spec 6.13).
    """
    res = await db.execute(select(AppConfig))
    rows = res.scalars().all()
    return [
        {"key": r.key, "value": r.value, "updated_at": r.updated_at.isoformat() if r.updated_at else None, "updated_by": str(r.updated_by) if r.updated_by else None}
        for r in rows
    ]


@router.put("/config")
async def update_config(
    payload: dict[str, Any],
    admin: Admin = Depends(require_admin(["owner", "editor"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Upsert runtime config keys, bump config_version, and bust server/client caches (Spec 6.13).
    """
    now = datetime.now(UTC)
    diff = {}

    for key, val in payload.items():
        stmt = select(AppConfig).where(AppConfig.key == key)
        res = await db.execute(stmt)
        existing = res.scalars().first()

        if existing:
            diff[key] = {"old": existing.value, "new": val}
            existing.value = val
            existing.updated_at = now
            existing.updated_by = admin.id
        else:
            diff[key] = {"old": None, "new": val}
            db.add(AppConfig(key=key, value=val, updated_at=now, updated_by=admin.id))

    new_version = await bump_config_version(db, admin.id)

    await log_audit_event(
        db=db,
        action="config_updated",
        target_type="app_config",
        target_id=f"version-{new_version}",
        actor_id=admin.id,
        metadata={"diff": diff, "version": new_version}
    )

    return {"updated": True, "config_version": new_version}


@router.get("/flags")
async def get_all_flags(
    admin: Admin = Depends(require_admin(["owner", "editor", "support"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all remote feature flags (Spec 6.13).
    """
    res = await db.execute(select(FeatureFlag))
    rows = res.scalars().all()
    return [
        {"key": r.key, "value": r.value, "updated_at": r.updated_at.isoformat() if r.updated_at else None, "updated_by": str(r.updated_by) if r.updated_by else None}
        for r in rows
    ]


@router.put("/flags")
async def update_flags(
    payload: dict[str, Any],
    admin: Admin = Depends(require_admin(["owner", "editor"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Upsert feature flags and record audit trail (Spec 6.13).
    """
    now = datetime.now(UTC)
    diff = {}

    for key, val in payload.items():
        stmt = select(FeatureFlag).where(FeatureFlag.key == key)
        res = await db.execute(stmt)
        existing = res.scalars().first()

        if existing:
            diff[key] = {"old": existing.value, "new": val}
            existing.value = val
            existing.updated_at = now
            existing.updated_by = admin.id
        else:
            diff[key] = {"old": None, "new": val}
            db.add(FeatureFlag(key=key, value=val, updated_at=now, updated_by=admin.id))

    await log_audit_event(
        db=db,
        action="flags_updated",
        target_type="feature_flags",
        target_id="bulk",
        actor_id=admin.id,
        metadata={"diff": diff}
    )

    return {"updated": True}
