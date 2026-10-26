"""Admin Audit Trail Log Inspection (Spec 5.10 & 6.14)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_admin
from app.models.admin import AuditLogItem
from app.models.common import PageResponse
from app.models.db_models import Admin, AuditLog

router = APIRouter(prefix="/v1/admin", tags=["Admin Audit"])


@router.get("/audit-log", response_model=PageResponse[AuditLogItem])
async def list_audit_logs(
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    offset: int = 0,
    limit: int = 50,
    admin: Admin = Depends(require_admin(["owner", "editor", "support"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Search and filter immutable append-only audit trail logs (Spec 6.14).
    """
    stmt = select(AuditLog)

    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)

    total_count = (await db.execute(select(func.count(AuditLog.id)))).scalar() or 0

    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    res = await db.execute(stmt)
    logs = res.scalars().all()

    items = [
        AuditLogItem(
            id=entry.id,
            actor_id=entry.actor_id,
            actor_email=None,
            action=entry.action,
            target_type=entry.target_type,
            target_id=entry.target_id,
            metadata=entry.metadata_json or {},
            created_at=entry.created_at
        )
        for entry in logs
    ]

    return PageResponse(items=items, offset=offset, limit=limit, total=total_count)
