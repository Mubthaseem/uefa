"""Common Pydantic Schemas matching Spec Section 6.0 & 6.1."""

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Client-safe error response object."""
    code: str = Field(..., description="Machine-readable error identifier")
    message: str = Field(..., description="Human-readable neutral error message")


class ErrorResponse(BaseModel):
    """Standard error envelope for all non-2xx responses."""
    error: ErrorDetail


class HealthResponse(BaseModel):
    """GET /healthz response."""
    status: str = "ok"
    version: str = "1.0.0"
    ts: datetime


T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    """Standard pagination envelope."""
    items: list[T]
    offset: int = 0
    limit: int = 20
    total: int = 0
