"""Admin API Endpoints Integration Tests (Spec Section 11.1 T07 - T13)."""

import pyotp
import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.models.db_models import Admin
from app.security import encrypt_aes_gcm, generate_totp_secret, hash_password
from app.tests.conftest import TestingSessionLocal

settings = get_settings()


@pytest.fixture
async def seeded_admin():
    """Create a test owner admin in the test database."""
    secret = generate_totp_secret()
    enc_secret = encrypt_aes_gcm(secret, settings.totp_encryption_key_bytes)
    pwd = "AdminSecurePassword123!"
    pwd_hash = hash_password(pwd)

    async with TestingSessionLocal() as session:
        admin = Admin(
            email="owner@dayjournal.app",
            password_hash=pwd_hash,
            mfa_secret=enc_secret,
            role="owner",
            disabled=False
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        return {"admin": admin, "password": pwd, "totp_secret": secret}


@pytest.mark.asyncio
async def test_admin_auth_and_session_flow(async_client: AsyncClient, seeded_admin: dict):
    """
    Test Admin 2-Factor Auth Flow (Spec 6.10):
    1. POST /v1/admin/login with email + password -> pending_token
    2. POST /v1/admin/mfa/verify with pending_token + TOTP -> access_token
    3. GET /v1/admin/session/me with access_token -> 200
    4. POST /v1/admin/logout -> 204
    5. GET /v1/admin/session/me after logout -> 401
    """
    admin_data = seeded_admin

    # 1. Login
    login_resp = await async_client.post(
        "/v1/admin/login",
        json={"email": "owner@dayjournal.app", "password": admin_data["password"]}
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert login_data["mfa_required"] is True
    pending_token = login_data["pending_token"]

    # 2. MFA Verify
    totp = pyotp.TOTP(admin_data["totp_secret"])
    code = totp.now()

    mfa_resp = await async_client.post(
        "/v1/admin/mfa/verify",
        json={"pending_token": pending_token, "totp": code}
    )
    assert mfa_resp.status_code == 200
    mfa_data = mfa_resp.json()
    admin_token = mfa_data["access_token"]
    assert mfa_data["admin"]["role"] == "owner"

    # 3. GET /session/me
    headers = {"Authorization": f"Bearer {admin_token}"}
    me_resp = await async_client.get("/v1/admin/session/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "owner@dayjournal.app"

    # 4. Logout
    logout_resp = await async_client.post("/v1/admin/logout", headers=headers)
    assert logout_resp.status_code == 204

    # 5. Token is revoked
    revoked_resp = await async_client.get("/v1/admin/session/me", headers=headers)
    assert revoked_resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_batches_and_single_export_rule(async_client: AsyncClient, seeded_admin: dict):
    """
    Test Admin Codes Batches & Export Rule (Spec 6.11):
    1. Login as owner
    2. POST /v1/admin/codes/batches -> creates 5 keys
    3. GET /v1/admin/codes/batches/{id} -> codes list (NEVER plaintext)
    4. GET /v1/admin/codes/batches/{id}/export -> CSV with plaintext
    5. GET export again -> 409 Conflict
    """
    admin_data = seeded_admin

    # Login & get admin token
    login_resp = await async_client.post(
        "/v1/admin/login",
        json={"email": "owner@dayjournal.app", "password": admin_data["password"]}
    )
    pending_token = login_resp.json()["pending_token"]
    code = pyotp.TOTP(admin_data["totp_secret"]).now()
    mfa_resp = await async_client.post(
        "/v1/admin/mfa/verify",
        json={"pending_token": pending_token, "totp": code}
    )
    admin_token = mfa_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Create Batch
    batch_resp = await async_client.post(
        "/v1/admin/codes/batches",
        json={"label": "VIP Q1 Release", "count": 5, "expires_in_days": 365},
        headers=headers
    )
    assert batch_resp.status_code == 201
    batch_id = batch_resp.json()["id"]

    # 2. Inspect Codes (Never plaintext)
    list_resp = await async_client.get(f"/v1/admin/codes/batches/{batch_id}", headers=headers)
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) == 5
    for item in items:
        assert "code" not in item  # Plaintext is NEVER returned here (Spec 6.11)
        assert item["status"] == "unused"

    # 3. Export CSV (First time success)
    export_resp = await async_client.get(f"/v1/admin/codes/batches/{batch_id}/export", headers=headers)
    assert export_resp.status_code == 200
    assert export_resp.headers["content-type"] == "text/csv; charset=utf-8"
    csv_text = export_resp.text
    assert "code,status,created_at,expires_at" in csv_text

    # 4. Export CSV second time -> 409 Conflict
    second_export = await async_client.get(f"/v1/admin/codes/batches/{batch_id}/export", headers=headers)
    assert second_export.status_code == 409
    assert second_export.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_admin_config_and_audit_trail(async_client: AsyncClient, seeded_admin: dict):
    """
    Test Admin Configuration Update & Audit Log (Spec 6.13 & 6.14):
    1. PUT /v1/admin/config -> bumps version
    2. GET /v1/admin/audit-log -> records config_updated action
    """
    admin_data = seeded_admin

    login_resp = await async_client.post(
        "/v1/admin/login",
        json={"email": "owner@dayjournal.app", "password": admin_data["password"]}
    )
    code = pyotp.TOTP(admin_data["totp_secret"]).now()
    mfa_resp = await async_client.post(
        "/v1/admin/mfa/verify",
        json={"pending_token": login_resp.json()["pending_token"], "totp": code}
    )
    headers = {"Authorization": f"Bearer {mfa_resp.json()['access_token']}"}

    # 1. Update config
    cfg_resp = await async_client.put(
        "/v1/admin/config",
        json={"brand.tagline": "Encrypted Personal Notes"},
        headers=headers
    )
    assert cfg_resp.status_code == 200
    assert cfg_resp.json()["updated"] is True
    new_version = cfg_resp.json()["config_version"]
    assert new_version >= 2

    # 2. Verify audit log recorded event
    audit_resp = await async_client.get("/v1/admin/audit-log", headers=headers)
    assert audit_resp.status_code == 200
    logs = audit_resp.json()["items"]
    assert any(entry["action"] == "config_updated" for entry in logs)
