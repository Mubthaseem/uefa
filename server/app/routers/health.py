"""Health Check Endpoint (Spec 6.2)."""

from datetime import UTC, datetime

from fastapi import APIRouter

from app.models.common import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/healthz", response_model=HealthResponse)
async def health_check():
    """
    Public health check endpoint utilized by Render and uptime monitors.
    """
    return HealthResponse(
        status="ok",
        version="1.0.0",
        ts=datetime.now(UTC)
    )
