from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .service import LicenseStatus


class LicenseStatusRead(BaseModel):
    state: str
    allowed: bool
    plan: str | None = None
    features: list[str] = Field(default_factory=list)
    expires_at: int | None = None
    grace_deadline: int | None = None
    detail: str | None = None

    @classmethod
    def of(cls, status: LicenseStatus) -> "LicenseStatusRead":
        return cls(
            state=status.state,
            allowed=status.allowed,
            plan=status.plan,
            features=status.features,
            expires_at=status.expires_at,
            grace_deadline=status.grace_deadline,
            detail=status.detail,
        )


class InstallEntitlementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The compact EdDSA entitlement the cloud issued (a capability token, not secret).
    entitlement_token: str = Field(min_length=1, max_length=8192)
