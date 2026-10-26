"""Admin Device Inspection and Management (Spec 6.12)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_admin
from app.models.admin import DeviceAdminDetail, DeviceAdminItem, DeviceUpdateIn
from app.models.common import PageResponse
from app.models.db_models import AccessKey, Admin, Device, Entitlement, RefreshToken
from app.services.audit_service import log_audit_event
from app.services.code_service import revoke_device_cascade

router = APIRouter(prefix="/v1/admin/devices", tags=["Admin Devices"])


@router.get("", response_model=PageResponse[DeviceAdminItem])
async def list_devices(
    q: str | None = None,
    status_filter: str | None = "all",
    offset: int = 0,
    limit: int = 20,
    admin: Admin = Depends(require_admin(["owner", "editor", "support"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Search and list enrolled devices with active entitlement status (Spec 6.12).
    """
    stmt = select(Device)

    if status_filter == "active":
        stmt = stmt.where(Device.revoked_at.is_(None))
    elif status_filter == "blocked":
        stmt = stmt.where(Device.revoked_at.is_not(None))

    # Count
    count_stmt = select(func.count(Device.id))
    total_count = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(Device.created_at.desc()).offset(offset).limit(limit)
    res = await db.execute(stmt)
    devices = res.scalars().all()

    items: list[DeviceAdminItem] = []
    for d in devices:
        # Check active entitlement
        ent_stmt = select(Entitlement.status).where(Entitlement.device_id == d.id).order_by(Entitlement.granted_at.desc())
        ent_status = (await db.execute(ent_stmt)).scalar()

        items.append(
            DeviceAdminItem(
                id=d.id,
                install_id=d.install_id,
                platform=d.platform,
                app_version=d.app_version,
                note=d.note,
                created_at=d.created_at,
                last_seen_at=d.last_seen_at,
                revoked_at=d.revoked_at,
                entitlement_status=ent_status
            )
        )

    return PageResponse(items=items, offset=offset, limit=limit, total=total_count)


@router.get("/{device_id}", response_model=DeviceAdminDetail)
async def get_device_detail(
    device_id: uuid.UUID,
    admin: Admin = Depends(require_admin(["owner", "editor", "support"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Detailed device inspection: entitlements, access keys, token history (Spec 6.12).
    """
    stmt = select(Device).where(Device.id == device_id)
    res = await db.execute(stmt)
    device = res.scalars().first()

    if not device:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Device not found."}})

    # Fetch entitlements
    ent_res = await db.execute(select(Entitlement).where(Entitlement.device_id == device_id))
    ents = [
        {"id": str(e.id), "status": e.status, "granted_at": e.granted_at.isoformat(), "expires_at": e.expires_at.isoformat() if e.expires_at else None}
        for e in ent_res.scalars().all()
    ]

    # Fetch keys
    keys_res = await db.execute(select(AccessKey).where(AccessKey.device_id == device_id))
    keys = [
        {"id": str(k.id), "status": k.status, "batch_id": str(k.batch_id), "redeemed_at": k.redeemed_at.isoformat() if k.redeemed_at else None}
        for k in keys_res.scalars().all()
    ]

    # Token count
    tokens_count = (await db.execute(select(func.count(RefreshToken.id)).where(RefreshToken.device_id == device_id))).scalar() or 0

    return DeviceAdminDetail(
        id=device.id,
        install_id=device.install_id,
        platform=device.platform,
        app_version=device.app_version,
        note=device.note,
        created_at=device.created_at,
        last_seen_at=device.last_seen_at,
        revoked_at=device.revoked_at,
        entitlements=ents,
        key_history=keys,
        token_count=tokens_count
    )


@router.post("/{device_id}/unbind")
async def unbind_device(
    device_id: uuid.UUID,
    admin: Admin = Depends(require_admin(["owner", "editor"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Unbind device: cascade revokes tokens and disassociates redeemed keys (Spec 6.12).
    """
    await revoke_device_cascade(db, device_id)
    await db.execute(
        update(AccessKey)
        .where(AccessKey.device_id == device_id, AccessKey.status == "redeemed")
        .values(device_id=None)
    )
    await db.flush()

    await log_audit_event(
        db=db,
        action="device_unbound",
        target_type="device",
        target_id=str(device_id),
        actor_id=admin.id
    )

    return {"unbound": True}


@router.post("/{device_id}/block")
async def block_device(
    device_id: uuid.UUID,
    admin: Admin = Depends(require_admin(["owner", "editor"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Block device permanently: sets revoked_at = now() and cascades revocation (Spec 6.12).
    """
    now = datetime.now(UTC)
    stmt = select(Device).where(Device.id == device_id)
    res = await db.execute(stmt)
    device = res.scalars().first()

    if not device:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Device not found."}})

    device.revoked_at = now
    await revoke_device_cascade(db, device_id)
    await db.flush()

    await log_audit_event(
        db=db,
        action="device_blocked",
        target_type="device",
        target_id=str(device_id),
        actor_id=admin.id
    )

    return {"blocked": True}


@router.patch("/{device_id}")
async def update_device_note(
    device_id: uuid.UUID,
    payload: DeviceUpdateIn,
    admin: Admin = Depends(require_admin(["owner", "editor", "support"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Update administrator note on a device record.
    """
    stmt = select(Device).where(Device.id == device_id)
    res = await db.execute(stmt)
    device = res.scalars().first()

    if not device:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Device not found."}})

    device.note = payload.note
    await db.flush()

    return {"updated": True}
