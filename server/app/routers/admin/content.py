"""Admin VIP Members Content & Media Management (Spec 5.13 & 6.14)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.deps import require_admin
from app.models.admin import MemberItemAdminOut, MemberItemCreateIn, MemberItemUpdateIn
from app.models.common import PageResponse
from app.models.db_models import Admin, MembersItem
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/v1/admin/members", tags=["Admin Content"])
settings = get_settings()


@router.get("/items", response_model=PageResponse[MemberItemAdminOut])
async def list_member_items(
    published: bool | None = None,
    offset: int = 0,
    limit: int = 20,
    admin: Admin = Depends(require_admin(["owner", "editor", "support"])),
    db: AsyncSession = Depends(get_db)
):
    """
    List VIP content catalogue items including drafts (Spec 6.14).
    """
    stmt = select(MembersItem)
    if published is not None:
        stmt = stmt.where(MembersItem.published == published)

    total_count = (await db.execute(select(func.count(MembersItem.id)))).scalar() or 0

    stmt = stmt.order_by(MembersItem.sort_order.asc(), MembersItem.created_at.desc()).offset(offset).limit(limit)
    res = await db.execute(stmt)
    items = res.scalars().all()

    out_items = [
        MemberItemAdminOut(
            id=i.id,
            item_type=i.item_type,
            title=i.title,
            description=i.description,
            media_ref=i.media_ref,
            thumbnail_ref=i.thumbnail_ref,
            duration_seconds=i.duration_seconds,
            sort_order=i.sort_order,
            published=i.published,
            min_app_version=i.min_app_version,
            created_at=i.created_at,
            updated_at=i.updated_at
        )
        for i in items
    ]

    return PageResponse(items=out_items, offset=offset, limit=limit, total=total_count)


@router.post("/items", response_model=MemberItemAdminOut, status_code=status.HTTP_201_CREATED)
async def create_member_item(
    payload: MemberItemCreateIn,
    admin: Admin = Depends(require_admin(["owner", "editor"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new VIP media item (Spec 6.14).
    """
    now = datetime.now(UTC)
    item = MembersItem(
        item_type=payload.item_type,
        title=payload.title,
        description=payload.description,
        media_ref=payload.media_ref,
        thumbnail_ref=payload.thumbnail_ref,
        duration_seconds=payload.duration_seconds,
        sort_order=payload.sort_order,
        published=payload.published,
        min_app_version=payload.min_app_version,
        created_at=now,
        updated_at=now
    )
    db.add(item)
    await db.flush()

    await log_audit_event(
        db=db,
        action="item_created",
        target_type="members_item",
        target_id=str(item.id),
        actor_id=admin.id,
        metadata={"title": item.title, "type": item.item_type}
    )

    return MemberItemAdminOut(
        id=item.id,
        item_type=item.item_type,
        title=item.title,
        description=item.description,
        media_ref=item.media_ref,
        thumbnail_ref=item.thumbnail_ref,
        duration_seconds=item.duration_seconds,
        sort_order=item.sort_order,
        published=item.published,
        min_app_version=item.min_app_version,
        created_at=item.created_at,
        updated_at=item.updated_at
    )


@router.put("/items/{item_id}", response_model=MemberItemAdminOut)
async def update_member_item(
    item_id: uuid.UUID,
    payload: MemberItemUpdateIn,
    admin: Admin = Depends(require_admin(["owner", "editor"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Update an existing VIP media item and log diff (Spec 6.14).
    """
    stmt = select(MembersItem).where(MembersItem.id == item_id)
    res = await db.execute(stmt)
    item = res.scalars().first()

    if not item:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Item not found."}})

    diff = {}
    for attr, val in payload.model_dump(exclude_unset=True).items():
        old_val = getattr(item, attr)
        if old_val != val:
            diff[attr] = {"old": old_val, "new": val}
            setattr(item, attr, val)

    item.updated_at = datetime.now(UTC)
    await db.flush()

    await log_audit_event(
        db=db,
        action="item_updated",
        target_type="members_item",
        target_id=str(item.id),
        actor_id=admin.id,
        metadata={"diff": diff}
    )

    return MemberItemAdminOut(
        id=item.id,
        item_type=item.item_type,
        title=item.title,
        description=item.description,
        media_ref=item.media_ref,
        thumbnail_ref=item.thumbnail_ref,
        duration_seconds=item.duration_seconds,
        sort_order=item.sort_order,
        published=item.published,
        min_app_version=item.min_app_version,
        created_at=item.created_at,
        updated_at=item.updated_at
    )


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member_item(
    item_id: uuid.UUID,
    admin: Admin = Depends(require_admin(["owner"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a VIP media item (owner role only).
    """
    stmt = select(MembersItem).where(MembersItem.id == item_id)
    res = await db.execute(stmt)
    item = res.scalars().first()

    if not item:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Item not found."}})

    await db.delete(item)
    await db.flush()

    await log_audit_event(
        db=db,
        action="item_deleted",
        target_type="members_item",
        target_id=str(item_id),
        actor_id=admin.id
    )
