"""Admin Access Codes & Batches Management (Spec 6.11)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_admin
from app.models.admin import BatchCreateIn, BatchCreateOut, BatchListItem, CodeListItem
from app.models.common import PageResponse
from app.models.db_models import AccessKey, Admin, KeyBatch
from app.services.audit_service import log_audit_event
from app.services.code_service import (
    export_batch_csv,
    generate_batch,
    revoke_device_cascade,
)

router = APIRouter(prefix="/v1/admin/codes", tags=["Admin Codes"])


@router.get("/batches", response_model=PageResponse[BatchListItem])
async def list_batches(
    offset: int = 0,
    limit: int = 20,
    admin: Admin = Depends(require_admin(["owner", "editor", "support"])),
    db: AsyncSession = Depends(get_db)
):
    """
    List all code batches with counts of redeemed keys (Spec 6.11).
    """
    total_stmt = select(func.count(KeyBatch.id))
    total_res = await db.execute(total_stmt)
    total_count = total_res.scalar() or 0

    batches_stmt = (
        select(KeyBatch)
        .order_by(KeyBatch.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    batches_res = await db.execute(batches_stmt)
    batches = batches_res.scalars().all()

    items: list[BatchListItem] = []
    for b in batches:
        # Count redeemed keys
        used_stmt = (
            select(func.count(AccessKey.id))
            .where(AccessKey.batch_id == b.id, AccessKey.status == "redeemed")
        )
        used_res = await db.execute(used_stmt)
        used_count = used_res.scalar() or 0

        items.append(
            BatchListItem(
                id=b.id,
                label=b.label,
                count=b.count,
                used=used_count,
                exported=b.exported_at is not None,
                created_at=b.created_at,
                expires_in_days=b.expires_in_days
            )
        )

    return PageResponse(
        items=items,
        offset=offset,
        limit=limit,
        total=total_count
    )


@router.post("/batches", response_model=BatchCreateOut, status_code=status.HTTP_201_CREATED)
async def create_batch(
    payload: BatchCreateIn,
    admin: Admin = Depends(require_admin(["owner", "editor"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new batch of access codes (Spec 6.11).
    Generates CSPRNG Crockford Base32 codes and stores encrypted plaintext for export.
    """
    batch, _ = await generate_batch(
        db=db,
        count=payload.count,
        label=payload.label,
        expires_in_days=payload.expires_in_days,
        admin_id=admin.id
    )

    await log_audit_event(
        db=db,
        action="batch_created",
        target_type="key_batch",
        target_id=str(batch.id),
        actor_id=admin.id,
        metadata={"count": batch.count, "label": batch.label}
    )

    return BatchCreateOut(id=batch.id, count=batch.count)


@router.get("/batches/{batch_id}", response_model=PageResponse[CodeListItem])
async def list_batch_codes(
    batch_id: uuid.UUID,
    offset: int = 0,
    limit: int = 50,
    admin: Admin = Depends(require_admin(["owner", "editor", "support"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Inspect codes in a batch (Plaintext is NEVER returned - Spec 6.11).
    """
    total_stmt = select(func.count(AccessKey.id)).where(AccessKey.batch_id == batch_id)
    total_res = await db.execute(total_stmt)
    total_count = total_res.scalar() or 0

    stmt = (
        select(AccessKey)
        .where(AccessKey.batch_id == batch_id)
        .order_by(AccessKey.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    res = await db.execute(stmt)
    keys = res.scalars().all()

    items = [
        CodeListItem(
            id=k.id,
            status=k.status,
            created_at=k.created_at,
            redeemed_at=k.redeemed_at,
            device_id=k.device_id
        )
        for k in keys
    ]

    return PageResponse(
        items=items,
        offset=offset,
        limit=limit,
        total=total_count
    )


@router.get("/batches/{batch_id}/export")
async def export_batch(
    batch_id: uuid.UUID,
    admin: Admin = Depends(require_admin(["owner"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Export plaintext CSV once only (owner role only - Spec 6.11).
    Immediately clears plaintext_ciphertext from database.
    """
    try:
        csv_data = await export_batch_csv(db, batch_id)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {"code": "conflict", "message": "Already exported."}}
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "Batch not found."}}
        )

    await log_audit_event(
        db=db,
        action="batch_exported",
        target_type="key_batch",
        target_id=str(batch_id),
        actor_id=admin.id
    )

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=batch-{batch_id}.csv"}
    )


@router.post("/{key_id}/revoke")
async def revoke_single_code(
    key_id: uuid.UUID,
    admin: Admin = Depends(require_admin(["owner", "editor"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Revoke a single access code with cascade (Spec 6.11).
    """
    stmt = select(AccessKey).where(AccessKey.id == key_id)
    res = await db.execute(stmt)
    key = res.scalars().first()

    if not key:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Key not found."}})

    key.status = "revoked"
    if key.device_id:
        await revoke_device_cascade(db, key.device_id)

    await db.flush()

    await log_audit_event(
        db=db,
        action="key_revoked",
        target_type="access_key",
        target_id=str(key.id),
        actor_id=admin.id
    )

    return {"revoked": True}


@router.post("/batches/{batch_id}/revoke")
async def revoke_entire_batch(
    batch_id: uuid.UUID,
    admin: Admin = Depends(require_admin(["owner", "editor"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Bulk revoke all codes in a batch (Spec 6.11).
    """
    keys_stmt = select(AccessKey).where(AccessKey.batch_id == batch_id)
    keys_res = await db.execute(keys_stmt)
    keys = keys_res.scalars().all()

    for k in keys:
        k.status = "revoked"
        if k.device_id:
            await revoke_device_cascade(db, k.device_id)

    await db.flush()

    await log_audit_event(
        db=db,
        action="batch_revoked",
        target_type="key_batch",
        target_id=str(batch_id),
        actor_id=admin.id,
        metadata={"count": len(keys)}
    )

    return {"revoked": True, "count": len(keys)}
