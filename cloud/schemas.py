"""API request/response models. StrictModel forbids unknown fields (same posture
as the desktop) so a malformed/hostile body is rejected, not silently accepted."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=1024)


class VerifyEmailRequest(StrictModel):
    token: str = Field(min_length=1, max_length=256)


class TokenRequest(StrictModel):
    """Authenticate + register/attach the device + start a session. The device
    proves possession by signing the canonical challenge for its public key."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)
    device_public_key: str = Field(min_length=1, max_length=128)
    device_signature: str = Field(min_length=1, max_length=128)
    device_name: str = Field(default="Windows PC", max_length=120)


class RefreshRequest(StrictModel):
    refresh_token: str = Field(min_length=1, max_length=256)


class LogoutRequest(StrictModel):
    refresh_token: str = Field(min_length=1, max_length=256)


class PasswordResetRequest(StrictModel):
    email: EmailStr


class PasswordResetConfirm(StrictModel):
    token: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=12, max_length=1024)


class RedeemRequest(StrictModel):
    activation_key: str = Field(min_length=1, max_length=128)


class TokenResponse(StrictModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # access-token lifetime in seconds


class EntitlementResponse(StrictModel):
    entitlement_token: str


class DeviceResponse(StrictModel):
    id: str
    name: str
    platform: str
    revoked: bool


class MessageResponse(StrictModel):
    status: str
