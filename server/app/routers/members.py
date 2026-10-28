"""VIP Members Catalogue & Item Detail Endpoints (Spec 6.7 & 6.8)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import rate_limiter, require_entitlement
from app.models.members import CatalogueResponse, ItemDetailOut
from app.services.item_service import get_catalogue, get_item_detail

router = APIRouter(prefix="/v1/members", tags=["Members"])


@router.get(
    "/catalogue",
    response_model=CatalogueResponse,
    dependencies=[
        Depends(require_entitlement),
        Depends(rate_limiter("members_cat", limit=30, window_seconds=60, by_ip=True))
    ]
)
async def get_members_catalogue(
    db: AsyncSession = Depends(get_db)
):
    """
    List published VIP items for entitled members (Spec 6.7).
    Media URLs are excluded; thumbnails carry 900s signed URLs.
    """
    items = await get_catalogue(db)
    return CatalogueResponse(items=items)


@router.get(
    "/items/{item_id}",
    response_model=ItemDetailOut,
    dependencies=[
        Depends(require_entitlement),
        Depends(rate_limiter("members_item", limit=60, window_seconds=60, by_ip=True))
    ]
)
async def get_members_item_detail(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve single item with fresh 600s signed media URL (Spec 6.8).
    Returns 404 Not Found if unpublished or non-existent.
    """
    item = await get_item_detail(db, item_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "not_found", "message": "Not found."}}
        )
    return item


from app.services.portal_service import get_portal_template, render_portal_html


@router.get(
    "/streams",
    response_class=HTMLResponse,
    dependencies=[Depends(require_entitlement)]
)
async def get_members_streaming_portal(
    request: Request,
    token: str = Query(None),
    install_id: str = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Server-rendered streaming portal with HLS.js video playback,
    multi-angle camera feeds, and FotMob live match statistics.
    Resolved dynamically from database (portal_templates) with file fallback.
    """
    template_str = await get_portal_template(db, slug="streaming_portal")
    rendered_html = render_portal_html(template_str, token=token or "", install_id=install_id or "")
    return HTMLResponse(content=rendered_html)

