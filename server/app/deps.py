"""FastAPI Security & Authentication Dependencies (Spec 6.0, 6.1, 6.15)."""

import uuid
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models.db_models import Admin, Entitlement
from app.redis import RedisService, get_redis
from app.security import get_default_keypair, verify_jwt

settings = get_settings()


def get_client_ip(request: Request) -> str:
    """Extract real client IP considering forward headers."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def get_bearer_token(authorization: str | None = Header(None)) -> str:
    """Extract Bearer token from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Session expired. Please try again."}}
        )
    return authorization.split("Bearer ", 1)[1].strip()


def get_public_key() -> str:
    """Get active public key PEM."""
    _, pub = get_default_keypair(settings.JWT_PRIVATE_KEY, settings.JWT_PUBLIC_KEY)
    return pub


async def require_client_token(
    token: str = Depends(get_bearer_token),
    redis: RedisService = Depends(get_redis)
) -> dict[str, Any]:
    """
    Validate EdDSA client access token with aud="client".
    """
    pub_key = get_public_key()
    try:
        claims = verify_jwt(token, pub_key, expected_aud="client")
        return claims
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Session expired. Please try again."}}
        )


async def require_entitlement(
    claims: dict[str, Any] = Depends(require_client_token),
    db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Assert that the authenticated client has an active VIP entitlement (Spec 6.7 & 6.8).
    """
    device_id_str = claims.get("sub")
    if not device_id_str or claims.get("ent") != "member":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "forbidden", "message": "Members area no longer active."}}
        )

    try:
        device_id = uuid.UUID(device_id_str)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "forbidden", "message": "Members area no longer active."}}
        )

    # Cross-check database for revocation or device blocking
    stmt = (
        select(Entitlement)
        .where(
            Entitlement.device_id == device_id,
            Entitlement.status == "active"
        )
    )
    result = await db.execute(stmt)
    active_entitlement = result.scalars().first()

    if not active_entitlement:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "forbidden", "message": "Members area no longer active."}}
        )

    return claims


def require_admin(allowed_roles: list[str] | None = None):
    """
    Dependency factory to require admin authentication and role guard (Spec 6.10).
    """
    async def _require_admin(
        token: str = Depends(get_bearer_token),
        db: AsyncSession = Depends(get_db),
        redis: RedisService = Depends(get_redis)
    ) -> Admin:
        pub_key = get_public_key()
        try:
            claims = verify_jwt(token, pub_key, expected_aud="admin")
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "unauthorized", "message": "Admin session expired."}}
            )

        jti = claims.get("jti")
        if jti and await redis.is_jti_blacklisted(jti):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "unauthorized", "message": "Session has been logged out."}}
            )

        admin_id_str = claims.get("sub")
        role = claims.get("role")

        if allowed_roles and role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "forbidden", "message": "Insufficient role permissions."}}
            )

        # Check DB to ensure admin is not disabled
        try:
            admin_uuid = uuid.UUID(admin_id_str)
        except Exception:
            raise HTTPException(status_code=401, detail={"error": {"code": "unauthorized", "message": "Invalid admin ID."}})

        stmt = select(Admin).where(Admin.id == admin_uuid)
        res = await db.execute(stmt)
        admin = res.scalars().first()

        if not admin or admin.disabled:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"error": {"code": "unauthorized", "message": "Account disabled or not found."}}
            )

        return admin

    return _require_admin


def rate_limiter(
    key_prefix: str,
    limit: int,
    window_seconds: int,
    by_ip: bool = True,
    by_install_id: bool = False
):
    """
    Configurable sliding-window rate limiter dependency.
    """
    async def _limiter(
        request: Request,
        response: Response,
        redis: RedisService = Depends(get_redis)
    ):
        parts = [key_prefix]
        if by_ip:
            parts.append(get_client_ip(request))
        if by_install_id:
            install_id = request.headers.get("X-Install-Id") or "no-install"
            parts.append(install_id)

        rate_key = ":".join(parts)
        allowed, remaining, reset = await redis.check_rate_limit(rate_key, limit, window_seconds)

        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset)

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": {"code": "rate_limited", "message": "Too many attempts. Try again later."}},
                headers={"Retry-After": str(reset)}
            )

    return _limiter
