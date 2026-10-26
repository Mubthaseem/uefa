"""Admin User Account Management (Spec 5.1 & 6.14)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.deps import require_admin
from app.models.admin import AdminCreateIn, AdminUpdateIn, AdminUserOut
from app.models.db_models import Admin
from app.security import (
    encrypt_aes_gcm,
    generate_totp_secret,
    get_totp_provisioning_uri,
    hash_password,
)
from app.services.audit_service import log_audit_event

router = APIRouter(prefix="/v1/admin/admins", tags=["Admin Users"])
settings = get_settings()


@router.get("", response_model=list[AdminUserOut])
async def list_admin_users(
    admin: Admin = Depends(require_admin(["owner"])),
    db: AsyncSession = Depends(get_db)
):
    """
    List all administrator accounts (owner role only - Spec 6.14).
    """
    res = await db.execute(select(Admin).order_by(Admin.created_at.asc()))
    admins = res.scalars().all()

    return [
        AdminUserOut(
            id=a.id,
            email=a.email,
            role=a.role,
            disabled=a.disabled,
            last_login_at=a.last_login_at,
            created_at=a.created_at
        )
        for a in admins
    ]


@router.post("", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
async def create_admin_user(
    payload: AdminCreateIn,
    admin: Admin = Depends(require_admin(["owner"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Enroll a new administrator with Argon2id password and encrypted TOTP secret (Spec 6.14).
    """
    # Check duplicate email
    existing = (await db.execute(select(Admin).where(Admin.email == payload.email))).scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {"code": "conflict", "message": "Email already registered."}}
        )

    # Hash password & generate TOTP
    pwd_hash = hash_password(payload.password)
    totp_secret = generate_totp_secret()
    enc_totp = encrypt_aes_gcm(totp_secret, settings.totp_encryption_key_bytes)
    setup_uri = get_totp_provisioning_uri(totp_secret, payload.email)

    now = datetime.now(UTC)
    new_admin = Admin(
        email=payload.email,
        password_hash=pwd_hash,
        mfa_secret=enc_totp,
        role=payload.role,
        disabled=False,
        created_at=now,
        updated_at=now
    )
    db.add(new_admin)
    await db.flush()

    await log_audit_event(
        db=db,
        action="admin_created",
        target_type="admin",
        target_id=str(new_admin.id),
        actor_id=admin.id,
        metadata={"email": new_admin.email, "role": new_admin.role}
    )

    return AdminUserOut(
        id=new_admin.id,
        email=new_admin.email,
        role=new_admin.role,
        disabled=new_admin.disabled,
        last_login_at=None,
        created_at=new_admin.created_at,
        totp_setup_uri=setup_uri
    )


@router.patch("/{admin_id}", response_model=AdminUserOut)
async def update_admin_user(
    admin_id: uuid.UUID,
    payload: AdminUpdateIn,
    admin: Admin = Depends(require_admin(["owner"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Modify admin privileges or status (owner role only - Spec 6.14).
    """
    target = (await db.execute(select(Admin).where(Admin.id == admin_id))).scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Admin not found."}})

    diff = {}
    if payload.role is not None:
        diff["role"] = {"old": target.role, "new": payload.role}
        target.role = payload.role
    if payload.disabled is not None:
        diff["disabled"] = {"old": target.disabled, "new": payload.disabled}
        target.disabled = payload.disabled
    if payload.password:
        target.password_hash = hash_password(payload.password)
        diff["password_reset"] = True

    target.updated_at = datetime.now(UTC)
    await db.flush()

    await log_audit_event(
        db=db,
        action="admin_updated",
        target_type="admin",
        target_id=str(target.id),
        actor_id=admin.id,
        metadata={"diff": diff}
    )

    return AdminUserOut(
        id=target.id,
        email=target.email,
        role=target.role,
        disabled=target.disabled,
        last_login_at=target.last_login_at,
        created_at=target.created_at
    )
