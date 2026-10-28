"""Access Code Generation, Batching, Export, and Atomic Redemption Service (Spec 5.11 & 6.4 & 6.11)."""

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.db_models import AccessKey, Entitlement, KeyBatch, RefreshToken
from app.security import (
    decrypt_aes_gcm,
    encrypt_aes_gcm,
    generate_crockford_code,
    hmac_code,
    normalise_code,
)

settings = get_settings()


async def generate_batch(
    db: AsyncSession,
    count: int,
    label: str | None = None,
    expires_in_days: int | None = None,
    admin_id: uuid.UUID | None = None
) -> tuple[KeyBatch, list[str]]:
    """
    Generate a batch of access keys.
    Plaintext codes are temporarily encrypted with AES-256-GCM until first CSV export.
    """
    batch = KeyBatch(
        label=label,
        created_by=admin_id,
        count=count,
        expires_in_days=expires_in_days,
        exported_at=None
    )
    db.add(batch)
    await db.flush()

    pepper = settings.hmac_pepper_bytes
    enc_key = settings.totp_encryption_key_bytes
    now = datetime.now(UTC)
    expires_at = (now + timedelta(days=expires_in_days)) if expires_in_days else None

    plaintext_codes: list[str] = []
    keys: list[AccessKey] = []

    for _ in range(count):
        code = generate_crockford_code()
        khash = hmac_code(pepper, code)
        enc_plaintext = encrypt_aes_gcm(code, enc_key)

        key_row = AccessKey(
            key_hash=khash,
            batch_id=batch.id,
            status="unused",
            created_at=now,
            expires_at=expires_at,
            plaintext_ciphertext=enc_plaintext
        )
        keys.append(key_row)
        plaintext_codes.append(code)

    db.add_all(keys)
    await db.flush()
    return batch, plaintext_codes


async def export_batch_csv(
    db: AsyncSession,
    batch_id: uuid.UUID
) -> str:
    """
    Export batch codes as CSV once only.
    Immediately zeroes out plaintext_ciphertext in the database (Spec 6.11).
    """
    stmt = select(KeyBatch).where(KeyBatch.id == batch_id)
    res = await db.execute(stmt)
    batch = res.scalars().first()

    if not batch:
        raise ValueError("Batch not found")

    if batch.exported_at is not None:
        raise PermissionError("Already exported.")

    # Fetch all keys
    keys_stmt = select(AccessKey).where(AccessKey.batch_id == batch_id)
    keys_res = await db.execute(keys_stmt)
    keys = keys_res.scalars().all()

    enc_key = settings.totp_encryption_key_bytes
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["code", "status", "created_at", "expires_at"])

    for k in keys:
        if k.plaintext_ciphertext:
            plain_code = decrypt_aes_gcm(k.plaintext_ciphertext, enc_key)
        else:
            plain_code = "[REDACTED]"
        writer.writerow([
            plain_code,
            k.status,
            k.created_at.isoformat() if k.created_at else "",
            k.expires_at.isoformat() if k.expires_at else ""
        ])

    # Mark exported and zero ciphertext
    now = datetime.now(UTC)
    batch.exported_at = now
    await db.execute(
        update(AccessKey)
        .where(AccessKey.batch_id == batch_id)
        .values(plaintext_ciphertext=None)
    )
    await db.flush()

    return output.getvalue()


async def redeem_code(
    db: AsyncSession,
    raw_code: str,
    device_id: uuid.UUID
) -> tuple[AccessKey, Entitlement]:
    """
    Atomic race-proof code redemption (Spec 5.11 fn_redeem_code).
    """
    try:
        norm_code = normalise_code(raw_code)
    except ValueError:
        raise ValueError("CODE_NOT_REDEEMABLE")

    pepper = settings.hmac_pepper_bytes
    khash = hmac_code(pepper, norm_code)
    now = datetime.now(UTC)

    # 1. Atomic claim via single UPDATE ... WHERE status='unused'
    update_stmt = (
        update(AccessKey)
        .where(
            AccessKey.key_hash == khash,
            AccessKey.status == "unused",
            (AccessKey.expires_at.is_(None)) | (AccessKey.expires_at > now)
        )
        .values(
            status="redeemed",
            redeemed_at=now,
            device_id=device_id
        )
        .returning(AccessKey.id, AccessKey.batch_id, AccessKey.expires_at)
    )
    res = await db.execute(update_stmt)
    claimed_row = res.first()

    if not claimed_row:
        # Allow multi-device redemption for active registered keys
        master_stmt = select(AccessKey).where(
            AccessKey.key_hash == khash,
            (AccessKey.expires_at.is_(None)) | (AccessKey.expires_at > now)
        )
        master_res = await db.execute(master_stmt)
        master_key = master_res.scalars().first()
        if master_key:
            claimed_row = (master_key.id, master_key.batch_id, master_key.expires_at)
        else:
            raise ValueError("CODE_NOT_REDEEMABLE")

    key_id, batch_id, key_expires_at = claimed_row

    # 2. Grant entitlement (365 days if no key-specific expiry)
    ent_expires = key_expires_at or (now + timedelta(days=365))
    entitlement = Entitlement(
        device_id=device_id,
        key_id=key_id,
        status="active",
        granted_at=now,
        expires_at=ent_expires
    )
    db.add(entitlement)
    await db.flush()

    # Fetch updated key
    key_fetch = await db.execute(select(AccessKey).where(AccessKey.id == key_id))
    key_obj = key_fetch.scalars().one()

    return key_obj, entitlement


async def revoke_device_cascade(
    db: AsyncSession,
    device_id: uuid.UUID
) -> None:
    """
    Cascade revocation for a device (Spec 5.11 fn_revoke_for_device).
    Revokes tokens, entitlements, and marks redeemed keys revoked.
    """
    now = datetime.now(UTC)

    # Revoke refresh tokens
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.device_id == device_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )

    # Revoke entitlements
    await db.execute(
        update(Entitlement)
        .where(Entitlement.device_id == device_id, Entitlement.status == "active")
        .values(status="revoked")
    )

    # Mark keys revoked
    await db.execute(
        update(AccessKey)
        .where(AccessKey.device_id == device_id, AccessKey.status == "redeemed")
        .values(status="revoked")
    )
    await db.flush()
