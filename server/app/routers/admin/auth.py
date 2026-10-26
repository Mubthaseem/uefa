"""Admin Authentication Endpoints (Spec 6.10)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.deps import get_bearer_token, get_client_ip, get_public_key, require_admin
from app.models.auth import (
    AdminAuthOut,
    AdminInfo,
    AdminLoginIn,
    AdminLoginOut,
    AdminMfaVerifyIn,
)
from app.models.db_models import Admin
from app.redis import RedisService, get_redis
from app.security import decrypt_aes_gcm, verify_jwt, verify_password, verify_totp
from app.services.audit_service import log_audit_event
from app.services.token_service import issue_admin_access_token, issue_mfa_pending_token

router = APIRouter(prefix="/v1/admin", tags=["Admin Auth"])
settings = get_settings()


@router.post("/login", response_model=AdminLoginOut)
async def admin_login(
    payload: AdminLoginIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: RedisService = Depends(get_redis)
):
    """
    Step 1 of Admin Authentication: Argon2id password verification (Spec 6.10).
    Rate limit: 5/min/IP.
    """
    client_ip = get_client_ip(request)
    limiter_key = f"admin_login:{client_ip}"
    allowed, _, _ = await redis.check_rate_limit(limiter_key, limit=5, window_seconds=60)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {"code": "rate_limited", "message": "Too many attempts. Try again later."}}
        )

    # Check email lock
    if await redis.is_locked_out(f"admin:lock:{payload.email}"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {"code": "rate_limited", "message": "Account temporarily locked. Try again in 15 minutes."}}
        )

    # Fetch admin
    stmt = select(Admin).where(Admin.email == payload.email)
    res = await db.execute(stmt)
    admin = res.scalars().first()

    # Constant time / uniform error to prevent user enumeration
    if not admin or admin.disabled or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "invalid_credentials", "message": "Invalid email or password."}}
        )

    # Issue single-use 60-second pending token
    pending_token, _ = issue_mfa_pending_token(admin.id)

    return AdminLoginOut(
        mfa_required=True,
        pending_token=pending_token
    )


@router.post("/mfa/verify", response_model=AdminAuthOut)
async def admin_mfa_verify(
    payload: AdminMfaVerifyIn,
    db: AsyncSession = Depends(get_db),
    redis: RedisService = Depends(get_redis)
):
    """
    Step 2 of Admin Authentication: TOTP MFA verification (Spec 6.10).
    5 failures locks account for 15 minutes.
    """
    pub_key = get_public_key()
    try:
        claims = verify_jwt(payload.pending_token, pub_key, expected_aud="mfa_pending")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "invalid_token", "message": "Pending token expired or invalid."}}
        )

    jti = claims.get("jti")
    if not jti or await redis.is_jti_blacklisted(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "invalid_token", "message": "Pending token has already been used."}}
        )

    # Blacklist pending token so it cannot be replayed
    await redis.blacklist_jti(jti, ttl_seconds=60)

    admin_id_str = claims.get("sub")
    try:
        admin_id = uuid.UUID(admin_id_str)
    except Exception:
        raise HTTPException(status_code=401, detail={"error": {"code": "invalid_token", "message": "Invalid admin token."}})

    stmt = select(Admin).where(Admin.id == admin_id)
    res = await db.execute(stmt)
    admin = res.scalars().first()

    if not admin or admin.disabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "invalid_credentials", "message": "Account not found or disabled."}}
        )

    lock_key = f"admin:lock:{admin.email}"
    if await redis.is_locked_out(lock_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {"code": "rate_limited", "message": "Account temporarily locked."}}
        )

    # Decrypt TOTP secret and verify
    totp_secret = decrypt_aes_gcm(admin.mfa_secret, settings.totp_encryption_key_bytes)
    is_valid = verify_totp(totp_secret, payload.totp)

    if not is_valid:
        # Check attempts
        fail_key = f"admin:totp_fail:{admin.email}"
        _, remaining, _ = await redis.check_rate_limit(fail_key, limit=5, window_seconds=900)
        if remaining <= 0:
            await redis.set_lockout(lock_key, duration_seconds=900)  # 15 minutes
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "invalid_totp", "message": "Invalid authentication code."}}
        )

    # Success: update last login and issue full admin token
    now = datetime.now(UTC)
    admin.last_login_at = now
    await db.flush()

    access_token, _ = issue_admin_access_token(admin.id, admin.role)

    await log_audit_event(
        db=db,
        action="admin_login",
        target_type="admin",
        target_id=str(admin.id),
        actor_id=admin.id
    )

    return AdminAuthOut(
        access_token=access_token,
        admin=AdminInfo(
            id=admin.id,
            email=admin.email,
            role=admin.role,
            last_login_at=admin.last_login_at
        )
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def admin_logout(
    token: str = Depends(get_bearer_token),
    admin: Admin = Depends(require_admin()),
    redis: RedisService = Depends(get_redis)
):
    """
    Revoke admin session by blacklisting JWT jti until expiration (Spec 6.10).
    """
    pub_key = get_public_key()
    try:
        claims = verify_jwt(token, pub_key, expected_aud="admin")
        jti = claims.get("jti")
        if jti:
            await redis.blacklist_jti(jti, ttl_seconds=settings.ADMIN_TOKEN_EXPIRE_SECONDS)
    except Exception:
        pass
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/session/me", response_model=AdminInfo)
async def get_admin_me(
    admin: Admin = Depends(require_admin())
):
    """
    Get profile information of currently logged in admin.
    """
    return AdminInfo(
        id=admin.id,
        email=admin.email,
        role=admin.role,
        last_login_at=admin.last_login_at
    )

@router.get("/dev-totp")
async def get_dev_totp(
    email: str = "owner@dayjournal.app",
    db: AsyncSession = Depends(get_db),
):
    """Dev-only helper to fetch active TOTP code for local testing."""
    stmt = select(Admin).where(Admin.email == email)
    res = await db.execute(stmt)
    admin = res.scalars().first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    import pyotp
    totp_secret = decrypt_aes_gcm(admin.mfa_secret, settings.totp_encryption_key_bytes)
    return {"totp": pyotp.TOTP(totp_secret).now(), "secret": totp_secret}
