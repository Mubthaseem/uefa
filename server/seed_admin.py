"""CLI Utility to seed or reset an initial Owner Administrator account (Spec 5.1 & 6.10)."""

import asyncio
import os
import sys
import uuid
import pyotp
from sqlalchemy import select

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import get_settings
from app.db import AsyncSessionLocal, init_tables
from app.models.db_models import Admin
from app.security import (
    encrypt_aes_gcm,
    generate_totp_secret,
    get_totp_provisioning_uri,
    hash_password
)

settings = get_settings()


async def seed_owner(email: str = "owner@dayjournal.app", password: str = "AdminPass123456!"):
    await init_tables()
    totp_secret = generate_totp_secret()
    enc_secret = encrypt_aes_gcm(totp_secret, settings.totp_encryption_key_bytes)
    pwd_hash = hash_password(password)

    async with AsyncSessionLocal() as session:
        # Check if admin already exists
        res = await session.execute(select(Admin).where(Admin.email == email))
        admin = res.scalars().first()

        if admin:
            admin.password_hash = pwd_hash
            admin.mfa_secret = enc_secret
            admin.disabled = False
            admin.role = "owner"
            print(f"[+] Updated existing admin account: {email}")
        else:
            admin = Admin(
                id=uuid.uuid4(),
                email=email,
                password_hash=pwd_hash,
                mfa_secret=enc_secret,
                role="owner",
                disabled=False
            )
            session.add(admin)
            print(f"[+] Created new owner admin account: {email}")

        await session.commit()

    uri = get_totp_provisioning_uri(totp_secret, email)
    totp = pyotp.TOTP(totp_secret)
    current_code = totp.now()

    print("\n" + "=" * 60)
    print("ADMIN CREDENTIALS FOR TESTING & DEPLOYMENT")
    print("=" * 60)
    print(f"Email:         {email}")
    print(f"Password:      {password}")
    print(f"TOTP Secret:   {totp_secret}")
    print(f"Current TOTP:  {current_code} (valid for 30s)")
    print(f"OTPAuth URI:   {uri}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "owner@dayjournal.app"
    password = sys.argv[2] if len(sys.argv) > 2 else "AdminPass123456!"
    asyncio.run(seed_owner(email, password))