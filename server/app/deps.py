"""FastAPI Security & Authentication Dependencies (Spec 6.0, 6.1, 6.15)."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models.db_models import Admin, Device, Entitlement
from app.redis import RedisService, get_redis
from app.security import get_default_keypair, sign_jwt, verify_jwt

settings = get_settings()


def get_client_ip(request: Request) -> str:
    """Extract real client IP considering forward headers."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


def get_optional_bearer_token(request: Request, authorization: str | None = Header(None)) -> str | None:
    """Extract Bearer token from Authorization header or 'token' query param for WebView."""
    if authorization and authorization.startswith("Bearer "):
        return authorization.split("Bearer ", 1)[1].strip()
    query_token = request.query_params.get("token")
    if query_token:
        return query_token.strip()
    return None


def get_bearer_token(request: Request, authorization: str | None = Header(None)) -> str:
    """Extract Bearer token or raise 401."""
    token = get_optional_bearer_token(request, authorization)
    if token:
        return token
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": {"code": "unauthorized", "message": "Session expired. Please try again."}}
    )


def get_public_key() -> str:
    """Get active public key PEM."""
    _, pub = get_default_keypair(settings.JWT_PRIVATE_KEY, settings.JWT_PUBLIC_KEY)
    return pub


async def require_client_token(
    request: Request,
    token: str | None = Depends(get_optional_bearer_token),
    db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Validate EdDSA client access token with aud="client".
    Falls back to install_id device check if token is expired or missing.
    """
    pub_key = get_public_key()
    if token:
        try:
            claims = verify_jwt(token, pub_key, expected_aud="client")
            return claims
        except Exception:
            pass

    # Fallback to device install_id
    install_id_str = request.headers.get("X-Install-ID") or request.query_params.get("install_id")
    if install_id_str:
        try:
            install_id_uuid = uuid.UUID(str(install_id_str).strip())
            stmt = select(Device).where(Device.install_id == install_id_uuid, Device.revoked_at.is_(None))
            res = await db.execute(stmt)
            device = res.scalar_one_or_none()
            if device:
                return {
                    "sub": str(device.id),
                    "aud": "client",
                    "install_id": str(device.install_id),
                    "ent": "member"
                }
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": {"code": "unauthorized", "message": "Session expired. Please try again."}}
    )


async def require_entitlement(
    request: Request,
    token: str | None = Depends(get_optional_bearer_token),
    db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    Assert that the authenticated client has an active VIP entitlement (Spec 6.7 & 6.8).
    Supports token validation with automatic fallback to device install_id entitlement check.
    """
    device_id: uuid.UUID | None = None
    install_id_val: str | None = None

    pub_key = get_public_key()
    if token:
        try:
            claims = verify_jwt(token, pub_key, expected_aud="client")
            if claims.get("ent") == "member" and claims.get("sub"):
                device_id = uuid.UUID(claims["sub"])
                install_id_val = claims.get("install_id")
        except Exception:
            pass

    if not device_id:
        install_id_str = request.headers.get("X-Install-ID") or request.query_params.get("install_id")
        if install_id_str:
            try:
                install_id_uuid = uuid.UUID(str(install_id_str).strip())
                stmt = select(Device).where(Device.install_id == install_id_uuid, Device.revoked_at.is_(None))
                res = await db.execute(stmt)
                device = res.scalar_one_or_none()
                if device:
                    device_id = device.id
                    install_id_val = str(device.install_id)
            except Exception:
                pass

    if not device_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Session expired. Please try again."}}
        )

    # Cross-check database for active entitlement
    now = datetime.now(timezone.utc)
    stmt = (
        select(Entitlement)
        .where(
            Entitlement.device_id == device_id,
            Entitlement.status == "active",
            (Entitlement.expires_at.is_(None) | (Entitlement.expires_at > now))
        )
    )
    result = await db.execute(stmt)
    active_entitlement = result.scalars().first()

    if not active_entitlement:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "forbidden", "message": "Members area no longer active."}}
        )

    return {
        "sub": str(device_id),
        "ent": "member",
        "aud": "client",
        "install_id": install_id_val or ""
    }


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
