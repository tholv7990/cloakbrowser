from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from ..schemas.common import StrictModel


def normalize_email(value: str) -> str:
    return value.strip().casefold()


class EmailPasswordRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=1024)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_owner_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("password cannot contain null characters")
        if not value.strip():
            raise ValueError("password cannot contain only whitespace")
        return value


class OwnerSetupRequest(EmailPasswordRequest):
    pass


class LoginRequest(EmailPasswordRequest):
    pass


class ChangePasswordRequest(StrictModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        if "\x00" in value or not value.strip():
            raise ValueError("new password is invalid")
        return value


class AuthStatus(StrictModel):
    setup_required: bool


class OwnerSessionRead(StrictModel):
    email: EmailStr
    csrf_token: str
    idle_expires_at: datetime
    absolute_expires_at: datetime
