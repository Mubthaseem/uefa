"""Device Registration and Deletion Endpoints (Spec 6.3 & 6.9)."""

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import rate_limiter, require_client_token
from app.models.db_models import Device, Entitlement
from app.models.device import (
    DeviceDeleteIn,
    DeviceDeleteOut,
    DeviceRegisterIn,
    DeviceRegisterOut,
    EntitlementSummary,
)
from app.services.audit_service import log_audit_event
from app.services.code_service import revoke_device_cascade

router = APIRouter(prefix="/v1/devices", tags=["Devices"])


@router.post(
    "/register",
    response_model=DeviceRegisterOut,
    dependencies=[Depends(rate_limiter("device_reg", limit=10, window_seconds=60, by_ip=True))]
)
async def register_device(
    payload: DeviceRegisterIn,
    db: AsyncSession = Depends(get_db)
):
    """
    Register or heartbeat client device (Spec 6.3).
    Rate limit: 10/min/IP.
    """
    now = datetime.now(UTC)
    note_data = json.dumps({"tz_offset_minutes": payload.tz_offset_minutes})

    # Find existing device by install_id
    stmt = select(Device).where(Device.install_id == payload.install_id)
    res = await db.execute(stmt)
    device = res.scalars().first()

    if device:
        # Check if device is blocked / revoked
        if device.revoked_at is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "forbidden", "message": "Access is no longer active."}}
            )
        # Update metadata
        device.platform = payload.platform
        device.app_version = payload.app_version
        device.last_seen_at = now
        device.note = note_data
    else:
        # Create fresh device
        device = Device(
            install_id=payload.install_id,
            platform=payload.platform,
            app_version=payload.app_version,
            note=note_data,
            created_at=now,
            last_seen_at=now
        )
        db.add(device)

    await db.flush()

    # Check active entitlement
    ent_stmt = (
        select(Entitlement)
        .where(
            Entitlement.device_id == device.id,
            Entitlement.status == "active"
        )
    )
    ent_res = await db.execute(ent_stmt)
    entitlement = ent_res.scalars().first()

    ent_summary = None
    if entitlement:
        ent_summary = EntitlementSummary(
            status=entitlement.status,
            expires_at=entitlement.expires_at
        )

    return DeviceRegisterOut(
        device_id=device.id,
        entitled=entitlement is not None,
        entitlement=ent_summary
    )


@router.post("/delete", response_model=DeviceDeleteOut)
async def delete_device(
    payload: DeviceDeleteIn,
    claims: dict = Depends(require_client_token),
    db: AsyncSession = Depends(get_db)
):
    """
    GDPR account and device unenrollment cascade (Spec 6.9).
    Requires bearer client JWT.
    """
    # Verify install_id matches JWT claim
    claim_install_id = claims.get("install_id")
    if str(payload.install_id) != str(claim_install_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "forbidden", "message": "Installation ID mismatch."}}
        )

    device_id_str = claims.get("sub")
    device_id = uuid.UUID(device_id_str)

    # 1. Cascade revoke all entitlements, tokens, and keys
    await revoke_device_cascade(db, device_id)

    # 2. Anonymize/delete device record
    stmt = select(Device).where(Device.id == device_id)
    res = await db.execute(stmt)
    device = res.scalars().first()
    if device:
        device.install_id = None
        device.note = "deleted"
        device.revoked_at = datetime.now(UTC)
        await db.flush()

    # 3. Audit log
    await log_audit_event(
        db=db,
        action="device_deleted",
        target_type="device",
        target_id=str(device_id),
        actor_id=None,
        metadata={"install_id": str(payload.install_id)}
    )

    return DeviceDeleteOut(deleted=True)
