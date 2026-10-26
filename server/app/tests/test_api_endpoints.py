"""API Endpoints Integration Tests (Spec Section 11.1 T01 - T13)."""

import uuid

import pytest
from httpx import AsyncClient

from app.models.db_models import MembersItem
from app.services.code_service import generate_batch
from app.tests.conftest import TestingSessionLocal


@pytest.mark.asyncio
async def test_healthz_endpoint(async_client: AsyncClient):
    """GET /healthz returns 200 with status ok and version."""
    response = await async_client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "1.0.0"
    assert "ts" in data
    assert "X-Request-Id" in response.headers


@pytest.mark.asyncio
async def test_device_registration_endpoint(async_client: AsyncClient):
    """POST /v1/devices/register enrols a new device."""
    install_id = str(uuid.uuid4())
    payload = {
        "install_id": install_id,
        "platform": "android",
        "app_version": "1.0.0",
        "tz_offset_minutes": 330
    }
    response = await async_client.post("/v1/devices/register", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "device_id" in data
    assert data["entitled"] is False
    assert data["entitlement"] is None


@pytest.mark.asyncio
async def test_runtime_config_and_etag_caching(async_client: AsyncClient):
    """GET /v1/config returns config contract and handles 304 Not Modified."""
    response = await async_client.get("/v1/config")
    assert response.status_code == 200
    data = response.json()
    assert data["app"]["name"] == "DayJournal"
    assert "members" in data
    assert "flags" in data

    etag = response.headers.get("ETag")
    assert etag is not None

    # Test If-None-Match conditional request
    cached_response = await async_client.get("/v1/config", headers={"If-None-Match": etag})
    assert cached_response.status_code == 304


@pytest.mark.asyncio
async def test_redeem_invalid_code_error_envelope(async_client: AsyncClient):
    """POST /v1/codes/redeem with invalid code returns 401 with standard error format."""
    install_id = str(uuid.uuid4())
    payload = {
        "code": "0000-0000-0000-0000",
        "install_id": install_id
    }
    response = await async_client.post("/v1/codes/redeem", json=payload)
    assert response.status_code == 401
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "invalid_request"
    assert data["error"]["message"] == "That code is not valid."


@pytest.mark.asyncio
async def test_refresh_invalid_token(async_client: AsyncClient):
    """POST /v1/auth/refresh with bogus token returns 401 invalid_refresh."""
    payload = {
        "refresh_token": "non_existent_token_string",
        "install_id": str(uuid.uuid4())
    }
    response = await async_client.post("/v1/auth/refresh", json=payload)
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "invalid_refresh"


@pytest.mark.asyncio
async def test_full_redemption_and_members_catalogue_flow(async_client: AsyncClient):
    """
    Full end-to-end flow:
    1. Register device
    2. Seed a valid code
    3. Redeem code -> get access and refresh tokens
    4. Access /v1/members/catalogue with JWT -> 200 OK
    5. Rotate refresh token -> new token pair
    6. Replay original refresh token -> 401 invalid_refresh
    """
    # 1. Register device
    install_id = str(uuid.uuid4())
    reg_resp = await async_client.post(
        "/v1/devices/register",
        json={"install_id": install_id, "platform": "android", "app_version": "1.0.0"}
    )
    assert reg_resp.status_code == 200

    # 2. Seed a test code and member item
    async with TestingSessionLocal() as session:
        batch, codes = await generate_batch(db=session, count=1, label="Test Batch")
        valid_code = codes[0]

        # Seed member item
        item = MembersItem(
            item_type="video",
            title="Episode 1",
            description="Welcome to DayJournal members.",
            media_ref="video/ep1.mp4",
            published=True,
            sort_order=0
        )
        session.add(item)
        await session.commit()

    # 3. Redeem code
    redeem_resp = await async_client.post(
        "/v1/codes/redeem",
        json={"code": valid_code, "install_id": install_id}
    )
    assert redeem_resp.status_code == 200
    redeem_data = redeem_resp.json()
    access_token = redeem_data["access_token"]
    refresh_token = redeem_data["refresh_token"]
    assert access_token is not None
    assert refresh_token is not None

    # 4. Access /v1/members/catalogue
    cat_resp = await async_client.get(
        "/v1/members/catalogue",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert cat_resp.status_code == 200
    cat_data = cat_resp.json()
    assert "items" in cat_data
    assert len(cat_data["items"]) >= 1
    assert cat_data["items"][0]["title"] == "Episode 1"

    # 5. Rotate refresh token
    rotate_resp = await async_client.post(
        "/v1/auth/refresh",
        json={"refresh_token": refresh_token, "install_id": install_id}
    )
    assert rotate_resp.status_code == 200
    new_token_data = rotate_resp.json()
    new_refresh_token = new_token_data["refresh_token"]
    assert new_refresh_token != refresh_token

    # 6. Replay original refresh token (Reuse Detection) -> 401
    replay_resp = await async_client.post(
        "/v1/auth/refresh",
        json={"refresh_token": refresh_token, "install_id": install_id}
    )
    assert replay_resp.status_code == 401
    assert replay_resp.json()["error"]["code"] == "invalid_refresh"
