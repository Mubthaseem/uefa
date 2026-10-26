"""Append-only audit logging service (Spec 5.10)."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import AuditLog


async def log_audit_event(
    db: AsyncSession,
    action: str,
    target_type: str,
    target_id: str | None = None,
    actor_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None
) -> AuditLog:
    """
    Append an immutable event to the audit_log table.
    """
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata_json=metadata or {}
    )
    db.add(entry)
    await db.flush()
    return entry
