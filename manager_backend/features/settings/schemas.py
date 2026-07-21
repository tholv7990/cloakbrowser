from __future__ import annotations

from typing import Literal

from pydantic import Field

from ...schemas.common import StrictModel


class ManagerPreferences(StrictModel):
    default_locale: str = Field(default="en-US", min_length=2, max_length=35)
    default_timezone: str = Field(default="America/New_York", min_length=1, max_length=60)
    default_test_before_launch: bool = True
    rows_per_page: Literal[10, 25, 50, 100] = 25
    theme: Literal["light", "dark", "system"] = "system"
    log_retention_days: int = Field(default=14, ge=1, le=3650)
    trash_retention_days: int = Field(default=30, ge=1, le=3650)


class SettingsPatch(StrictModel):
    default_locale: str | None = Field(default=None, min_length=2, max_length=35)
    default_timezone: str | None = Field(default=None, min_length=1, max_length=60)
    default_test_before_launch: bool | None = None
    rows_per_page: Literal[10, 25, 50, 100] | None = None
    theme: Literal["light", "dark", "system"] | None = None
    log_retention_days: int | None = Field(default=None, ge=1, le=3650)
    trash_retention_days: int | None = Field(default=None, ge=1, le=3650)


class BrowserSettingsRead(StrictModel):
    name: str
    version: str
    path: str
    platform: str
    tier: Literal["free", "pro"]
    installed: bool
    update_available: bool
    latest_version: str | None


class LicenseSettingsRead(StrictModel):
    configured: bool
    valid: bool | None
    plan: str | None
    expires: str | None
    active_sessions: int | None
    session_limit: int | None


class SettingsRead(ManagerPreferences):
    profile_root: str
    report_root: str
    browser: BrowserSettingsRead
    license: LicenseSettingsRead
