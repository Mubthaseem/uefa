"""Admin Portal Template Management Router."""

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_admin
from app.models.db_models import Admin, PortalTemplate
from app.services.audit_service import log_audit_event
from app.services.portal_service import (
    get_file_template,
    get_portal_template,
    reset_portal_template_to_file,
    update_portal_template,
)

router = APIRouter(prefix="/portal-template", tags=["Admin Portal Template"])


class PortalTemplateUpdate(BaseModel):
    html_content: str = Field(..., min_length=10, description="Raw HTML template markup")
    title: str | None = Field(None, max_length=128, description="Human-readable title")
    slug: str = Field("streaming_portal", max_length=64, description="Template identifier slug")


@router.get("")
async def get_active_portal_template(
    slug: str = "streaming_portal",
    admin: Admin = Depends(require_admin(["owner", "editor", "support"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the currently active portal template.
    Indicates whether it is served from the database or falling back to the file system.
    """
    stmt = select(PortalTemplate).where(
        PortalTemplate.slug == slug,
        PortalTemplate.is_active == True
    )
    res = await db.execute(stmt)
    record = res.scalars().first()

    if record:
        return {
            "id": str(record.id),
            "slug": record.slug,
            "title": record.title,
            "version": record.version,
            "is_active": record.is_active,
            "source": "database",
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "html_content": record.html_content
        }

    file_html = get_file_template(f"{slug}.html")
    return {
        "id": None,
        "slug": slug,
        "title": "Static File Fallback",
        "version": 1,
        "is_active": True,
        "source": "file",
        "updated_at": None,
        "html_content": file_html
    }


@router.put("")
async def update_active_portal_template(
    payload: PortalTemplateUpdate,
    admin: Admin = Depends(require_admin(["owner", "editor"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Update or insert a custom HTML streaming portal template in the database.
    Increments the template version and takes effect immediately without redeploying code.
    """
    record = await update_portal_template(
        db=db,
        slug=payload.slug,
        new_html=payload.html_content,
        title=payload.title
    )

    await log_audit_event(
        db=db,
        action="portal_template_updated",
        target_type="portal_template",
        target_id=payload.slug,
        actor_id=admin.id,
        metadata={"version": record.version, "title": record.title}
    )

    return {
        "success": True,
        "slug": record.slug,
        "title": record.title,
        "version": record.version,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None
    }


@router.post("/reset")
async def reset_portal_template(
    slug: str = "streaming_portal",
    admin: Admin = Depends(require_admin(["owner", "editor"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Revert the database portal template back to the static file on disk.
    """
    record = await reset_portal_template_to_file(db=db, slug=slug)

    await log_audit_event(
        db=db,
        action="portal_template_reset",
        target_type="portal_template",
        target_id=slug,
        actor_id=admin.id,
        metadata={"version": record.version, "reset_to": "file"}
    )

    return {
        "success": True,
        "message": f"Template '{slug}' has been reset to disk file contents.",
        "slug": record.slug,
        "version": record.version,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None
    }
