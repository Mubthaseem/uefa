"""VIP Members Catalogue & Item Detail Endpoints (Spec 6.7 & 6.8)."""

import uuid
from typing import Any

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


from app.config import get_settings
from app.security import get_default_keypair, sign_jwt, verify_jwt
from app.services.portal_service import get_portal_template, render_portal_html

settings = get_settings()


@router.get(
    "/streams",
    response_class=HTMLResponse
)
async def get_members_streaming_portal(
    request: Request,
    token: str = Query(None),
    install_id: str = Query(None),
    auth: dict[str, Any] = Depends(require_entitlement),
    db: AsyncSession = Depends(get_db)
):
    """
    Server-rendered streaming portal with HLS.js video playback,
    multi-angle camera feeds, and FotMob live match statistics.
    Resolved dynamically from database (portal_templates) with file fallback.
    Guarantees a valid access token is always injected into the HTML.
    """
    active_token = token
    pub_key = get_default_keypair(settings.JWT_PRIVATE_KEY, settings.JWT_PUBLIC_KEY)[1]
    is_valid = False
    if active_token:
        try:
            verify_jwt(active_token, pub_key, expected_aud="client")
            is_valid = True
        except Exception:
            is_valid = False

    if not is_valid:
        priv_key, _ = get_default_keypair(settings.JWT_PRIVATE_KEY, settings.JWT_PUBLIC_KEY)
        active_token = sign_jwt(
            payload={
                "sub": str(auth["sub"]),
                "aud": "client",
                "ent": "member",
                "install_id": str(auth.get("install_id") or install_id or "")
            },
            private_key_pem=priv_key,
            kid=settings.JWT_KID,
            expires_in_seconds=settings.ACCESS_TOKEN_EXPIRE_SECONDS
        )

    resolved_install_id = install_id or auth.get("install_id") or ""
    template_str = await get_portal_template(db, slug="streaming_portal")
    rendered_html = render_portal_html(template_str, token=active_token, install_id=resolved_install_id)
    return HTMLResponse(content=rendered_html)

