"""Access Code Redemption Router (Spec 6.4 & 9.1)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_client_ip
from app.models.code import CodeRedeemIn, CodeRedeemOut
from app.models.db_models import Device
from app.models.device import EntitlementSummary
from app.redis import RedisService, get_redis
from app.services.audit_service import log_audit_event
from app.services.code_service import redeem_code
from app.services.token_service import create_refresh_token, issue_client_access_token

router = APIRouter(prefix="/v1/codes", tags=["Codes"])


@router.post("/redeem", response_model=CodeRedeemOut)
async def redeem_access_code(
    payload: CodeRedeemIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: RedisService = Depends(get_redis)
):
    """
    Atomic race-proof code redemption (Spec 6.4).
    Rate limit: 5 per 10 minutes per IP & install_id, followed by 60-min lockout.
    """
    client_ip = get_client_ip(request)
    limiter_key = f"redeem:{client_ip}:{payload.install_id}"

    # 1. Check if currently in 60-min lockout
    if await redis.is_locked_out(limiter_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {"code": "rate_limited", "message": "Too many attempts. Try again later."}},
            headers={"Retry-After": "3600"}
        )

    # 2. Sliding window check: 5 attempts per 10 mins (600s)
    allowed, remaining, reset = await redis.check_rate_limit(limiter_key, limit=5, window_seconds=600)
    response.headers["X-RateLimit-Limit"] = "5"
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset)

    if not allowed:
        # Trigger 60-minute lockout (3600s)
        await redis.set_lockout(limiter_key, duration_seconds=3600)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": {"code": "rate_limited", "message": "Too many attempts. Try again later."}},
            headers={"Retry-After": "3600"}
        )

    # 3. Lookup or enroll device
    now = datetime.now(UTC)
    stmt = select(Device).where(Device.install_id == payload.install_id)
    res = await db.execute(stmt)
    device = res.scalars().first()

    if not device:
        device = Device(
            install_id=payload.install_id,
            platform="android",
            created_at=now,
            last_seen_at=now
        )
        db.add(device)
        await db.flush()

    if device.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "forbidden", "message": "Access is no longer active."}}
        )

    # 4. Atomic claim via code_service
    try:
        access_key, entitlement = await redeem_code(
            db=db,
            raw_code=payload.code,
            device_id=device.id
        )
    except ValueError:
        # Generic error message regardless of used/revoked/expired/wrong (Spec 6.1 & 6.4)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "invalid_request", "message": "That code is not valid."}}
        )

    # 5. Issue token pair
    access_token = issue_client_access_token(
        device_id=device.id,
        install_id=device.install_id,
        app_version=device.app_version or "1.0.0",
        is_member=True
    )
    raw_refresh_token, _ = await create_refresh_token(
        db=db,
        device_id=device.id
    )

    # 6. Audit log event
    await log_audit_event(
        db=db,
        action="code_redeemed",
        target_type="access_key",
        target_id=str(access_key.id),
        metadata={"device_id": str(device.id), "batch_id": str(access_key.batch_id)}
    )

    return CodeRedeemOut(
        access_token=access_token,
        expires_in=900,
        token_type="bearer",
        refresh_token=raw_refresh_token,
        entitlement=EntitlementSummary(
            status=entitlement.status,
            expires_at=entitlement.expires_at
        )
    )
