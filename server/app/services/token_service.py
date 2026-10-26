"""Token issuance, verification, rotation, and reuse detection service (Spec 6.5 & 6.15)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.db_models import Entitlement, RefreshToken
from app.security import (
    generate_opaque_token,
    get_default_keypair,
    hash_opaque_token,
    sign_jwt,
)

settings = get_settings()


def get_private_key() -> str:
    priv, _ = get_default_keypair(settings.JWT_PRIVATE_KEY, settings.JWT_PUBLIC_KEY)
    return priv


def issue_client_access_token(
    device_id: uuid.UUID,
    install_id: uuid.UUID,
    app_version: str = "1.0.0",
    is_member: bool = True
) -> str:
    """Issue 15-minute EdDSA client JWT (aud: client)."""
    priv_key = get_private_key()
    claims = {
        "sub": str(device_id),
        "install_id": str(install_id),
        "ver": app_version,
        "ent": "member" if is_member else None,
        "aud": "client"
    }
    return sign_jwt(
        payload=claims,
        private_key_pem=priv_key,
        kid=settings.JWT_KID,
        expires_in_seconds=settings.ACCESS_TOKEN_EXPIRE_SECONDS
    )


def issue_admin_access_token(admin_id: uuid.UUID, role: str) -> tuple[str, str]:
    """Issue 30-minute EdDSA admin JWT (aud: admin). Returns (token, jti)."""
    priv_key = get_private_key()
    jti = str(uuid.uuid4())
    claims = {
        "sub": str(admin_id),
        "role": role,
        "aud": "admin",
        "jti": jti
    }
    token = sign_jwt(
        payload=claims,
        private_key_pem=priv_key,
        kid=settings.JWT_KID,
        expires_in_seconds=settings.ADMIN_TOKEN_EXPIRE_SECONDS
    )
    return token, jti


def issue_mfa_pending_token(admin_id: uuid.UUID) -> tuple[str, str]:
    """Issue 60-second EdDSA MFA pending JWT (aud: mfa_pending). Returns (token, jti)."""
    priv_key = get_private_key()
    jti = str(uuid.uuid4())
    claims = {
        "sub": str(admin_id),
        "aud": "mfa_pending",
        "jti": jti
    }
    token = sign_jwt(
        payload=claims,
        private_key_pem=priv_key,
        kid=settings.JWT_KID,
        expires_in_seconds=settings.MFA_PENDING_EXPIRE_SECONDS
    )
    return token, jti


async def create_refresh_token(
    db: AsyncSession,
    device_id: uuid.UUID,
    family_id: uuid.UUID | None = None
) -> tuple[str, RefreshToken]:
    """
    Generate and store an opaque 30-day rotating refresh token.
    """
    raw_token = generate_opaque_token()
    token_hash = hash_opaque_token(raw_token)
    fam_id = family_id or uuid.uuid4()
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    token_row = RefreshToken(
        device_id=device_id,
        token_hash=token_hash,
        family_id=fam_id,
        issued_at=now,
        expires_at=expires_at,
        revoked_at=None
    )
    db.add(token_row)
    await db.flush()
    return raw_token, token_row


async def rotate_refresh_token(
    db: AsyncSession,
    raw_refresh_token: str,
    install_id: uuid.UUID
) -> tuple[str | None, uuid.UUID | None]:
    """
    Rotate refresh token with reuse detection (Spec 6.5).
    
    Returns: (new_raw_refresh_token, device_id) on success,
    or (None, None) if invalid, expired, or replayed.
    """
    token_hash = hash_opaque_token(raw_refresh_token)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    res = await db.execute(stmt)
    token_row = res.scalars().first()

    now = datetime.now(UTC)

    # 1. Unknown token or expired
    if not token_row:
        return None, None

    # Handle naive / aware datetime
    row_expires = token_row.expires_at
    if row_expires.tzinfo is None:
        row_expires = row_expires.replace(tzinfo=UTC)
    if row_expires < now:
        return None, None

    # 2. Replay Detection (revoked_at is NOT NULL)
    if token_row.revoked_at is not None:
        # Revoke entire token family
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token_row.family_id)
            .values(revoked_at=now)
        )
        # Cascade revoke entitlements for this device
        await db.execute(
            update(Entitlement)
            .where(Entitlement.device_id == token_row.device_id)
            .values(status="revoked")
        )
        await db.commit()
        return None, None

    # 3. Valid token: revoke this token and issue new token in same family
    token_row.revoked_at = now
    new_raw, _ = await create_refresh_token(
        db=db,
        device_id=token_row.device_id,
        family_id=token_row.family_id
    )
    await db.flush()
    return new_raw, token_row.device_id
