"""Runtime Configuration Endpoint (Spec 6.6)."""


from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.config_api import ConfigOut
from app.services.config_service import assemble_runtime_config

router = APIRouter(prefix="/v1", tags=["Config"])


@router.get("/config", response_model=ConfigOut)
async def get_runtime_config(
    response: Response,
    if_none_match: str | None = Header(None, alias="If-None-Match"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get full dynamic runtime configuration with ETag caching (Spec 6.6).
    This is the ONLY contract surface the mobile client trusts.
    """
    config_obj = await assemble_runtime_config(db)
    etag_val = f'"{config_obj.config_version}"'
    unquoted_etag = str(config_obj.config_version)

    # Check ETag match for 304 Not Modified
    if if_none_match and (if_none_match == etag_val or if_none_match == unquoted_etag):
        response.status_code = status.HTTP_304_NOT_MODIFIED
        return response

    response.headers["ETag"] = etag_val
    response.headers["Cache-Control"] = "public, max-age=300"
    return config_obj
