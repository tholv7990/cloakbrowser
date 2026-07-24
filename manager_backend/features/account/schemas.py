from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .service import AccountStatus


class AccountStatusRead(BaseModel):
    cloud_configured: bool
    signed_in: bool
    email: str | None = None

    @classmethod
    def of(cls, status: AccountStatus) -> "AccountStatusRead":
        return cls(
            cloud_configured=status.cloud_configured,
            signed_in=status.signed_in,
            email=status.email,
        )


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class ActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activation_key: str = Field(min_length=1, max_length=128)
