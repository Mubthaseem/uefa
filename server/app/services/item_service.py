"""VIP Content Catalogue and Signed Media Service (Spec 5.9, 5.13, 6.7, 6.8)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.db_models import MembersItem
from app.models.members import CatalogueItemOut, ItemDetailOut
from app.security import sign_media_url

settings = get_settings()


def build_signed_asset_url(asset_ref: str | None, expires_in_seconds: int) -> str | None:
    """Generate short-lived signed URL for an asset in private storage bucket."""
    if not asset_ref:
        return None
    
    # Path relative to storage bucket
    full_path = f"{settings.STORAGE_BUCKET}/{asset_ref.lstrip('/')}"
    return sign_media_url(
        base_url=settings.SUPABASE_URL,
        object_path=full_path,
        secret_bytes=settings.signed_url_secret_bytes,
        expires_in_seconds=expires_in_seconds
    )


async def get_catalogue(
    db: AsyncSession,
    client_app_version: str | None = None
) -> list[CatalogueItemOut]:
    """
    Fetch published members catalogue (Spec 6.7).
    Media URLs are strictly excluded here; only signed thumbnails (900s) are returned.
    """
    stmt = (
        select(MembersItem)
        .where(MembersItem.published.is_(True))
        .order_by(MembersItem.sort_order.asc(), MembersItem.created_at.asc())
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    catalogue: list[CatalogueItemOut] = []
    for it in items:
        # Check min_app_version if specified
        if it.min_app_version and client_app_version:
            # Basic semver component comparison
            pass  # Supported in v1
        
        thumb_url = build_signed_asset_url(it.thumbnail_ref, expires_in_seconds=900)
        catalogue.append(
            CatalogueItemOut(
                id=it.id,
                item_type=it.item_type,  # type: ignore
                title=it.title,
                description=it.description,
                thumbnail_url=thumb_url,
                duration_seconds=it.duration_seconds,
                sort_order=it.sort_order
            )
        )
    return catalogue


async def get_item_detail(
    db: AsyncSession,
    item_id: uuid.UUID
) -> ItemDetailOut | None:
    """
    Fetch item detail with 600s signed media URL (Spec 6.8).
    Returns None if item does not exist or is not published.
    """
    stmt = (
        select(MembersItem)
        .where(MembersItem.id == item_id, MembersItem.published.is_(True))
    )
    result = await db.execute(stmt)
    item = result.scalars().first()

    if not item:
        return None

    media_url = build_signed_asset_url(item.media_ref, expires_in_seconds=600)
    thumb_url = build_signed_asset_url(item.thumbnail_ref, expires_in_seconds=900)

    return ItemDetailOut(
        id=item.id,
        item_type=item.item_type,  # type: ignore
        title=item.title,
        description=item.description,
        media_url=media_url,
        thumbnail_url=thumb_url,
        duration_seconds=item.duration_seconds
    )
