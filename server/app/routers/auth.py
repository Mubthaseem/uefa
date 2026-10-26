"""Client Authentication & Refresh Endpoints (Spec 6.5 & 6.15)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import rate_limiter
from app.models.auth import RefreshIn, TokenPairOut
from app.models.db_models import Device, Entitlement
from app.security import get_default_keypair
from app.services.token_service import issue_client_access_token, rotate_refresh_token

router = APIRouter(prefix="/v1", tags=["Authentication"])


@router.post(
    "/auth/refresh",
    response_model=TokenPairOut,
    dependencies=[Depends(rate_limiter("refresh", limit=10, window_seconds=60, by_ip=False, by_install_id=True))]
)
async def refresh_access_token(
    payload: RefreshIn,
    db: AsyncSession = Depends(get_db)
):
    """
    Rotate refresh token with automated reuse detection and family revocation (Spec 6.5).
    Rate limit: 10/min/install_id.
    """
    new_refresh_token, device_id = await rotate_refresh_token(
        db=db,
        raw_refresh_token=payload.refresh_token,
        install_id=payload.install_id
    )

    if not new_refresh_token or not device_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "invalid_refresh", "message": "Session expired. Please try again."}}
        )

    # Check device and entitlement status
    stmt = select(Device).where(Device.id == device_id)
    dev_res = await db.execute(stmt)
    device = dev_res.scalars().first()

    if not device or device.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "forbidden", "message": "Access is no longer active."}}
        )

    ent_stmt = select(Entitlement).where(Entitlement.device_id == device_id, Entitlement.status == "active")
    ent_res = await db.execute(ent_stmt)
    has_entitlement = ent_res.scalars().first() is not None

    access_token = issue_client_access_token(
        device_id=device.id,
        install_id=device.install_id or payload.install_id,
        app_version=device.app_version or "1.0.0",
        is_member=has_entitlement
    )

    return TokenPairOut(
        access_token=access_token,
        expires_in=900,
        token_type="bearer",
        refresh_token=new_refresh_token
    )


@router.get("/.well-known/jwks.json")
async def get_jwks():
    """
    Exposes public keys for EdDSA token signature verification.
    """
    from app.config import get_settings
    settings = get_settings()
    _, pub_pem = get_default_keypair(settings.JWT_PRIVATE_KEY, settings.JWT_PUBLIC_KEY)

    return {
        "keys": [
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "kid": settings.JWT_KID,
                "use": "sig",
                "alg": "EdDSA",
                "x5c": [pub_pem.replace("-----BEGIN PUBLIC KEY-----", "").replace("-----END PUBLIC KEY-----", "").strip()]
            }
        ]
    }
