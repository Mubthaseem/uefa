"""Code Redemption Schemas (Spec 6.4)."""

import uuid

from pydantic import BaseModel, Field

from app.models.device import EntitlementSummary


class CodeRedeemIn(BaseModel):
    """POST /v1/codes/redeem request body."""
    code: str = Field(..., max_length=32, description="Access code in XXXX-XXXX-XXXX-XXXX format")
    install_id: uuid.UUID = Field(..., description="Device installation UUIDv4")


class CodeRedeemOut(BaseModel):
    """POST /v1/codes/redeem response body."""
    access_token: str = Field(..., description="EdDSA signed JWT access token (15 mins)")
    expires_in: int = Field(default=900, description="Token lifetime in seconds")
    token_type: str = Field(default="bearer", description="Token type")
    refresh_token: str = Field(..., description="Opaque rotating refresh token (30 days)")
    entitlement: EntitlementSummary = Field(..., description="Active entitlement details")
