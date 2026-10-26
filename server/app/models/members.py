"""VIP Members Catalogue & Item Schemas (Spec 6.7 & 6.8)."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class CatalogueItemOut(BaseModel):
    """Single item entry in members catalogue list (excludes media_url)."""
    id: uuid.UUID
    item_type: Literal["video", "audio", "text"]
    title: str
    description: str | None = None
    thumbnail_url: str | None = None
    duration_seconds: int | None = None
    sort_order: int = 0


class CatalogueResponse(BaseModel):
    """GET /v1/members/catalogue response body."""
    items: list[CatalogueItemOut]


class ItemDetailOut(BaseModel):
    """GET /v1/members/items/{id} response with short-lived signed media URL."""
    id: uuid.UUID
    item_type: Literal["video", "audio", "text"]
    title: str
    description: str | None = None
    media_url: str | None = Field(None, description="Signed URL valid for 600s")
    thumbnail_url: str | None = Field(None, description="Signed thumbnail URL valid for 900s")
    duration_seconds: int | None = None
