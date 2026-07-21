from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from ...schemas.common import Page, StrictModel


_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){3,4}$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_MANAGER_ARG_KEYS = {
    "--fingerprint",
    "--fingerprint-platform",
    "--fingerprint-noise",
    "--fingerprint-storage-quota",
    "--fingerprint-timezone",
    "--fingerprint-locale",
    "--fingerprint-webrtc-ip",
    "--proxy-server",
    "--proxy-bypass-list",
    "--user-data-dir",
    "--remote-debugging-port",
    "--remote-debugging-pipe",
    "--load-extension",
    "--disable-extensions-except",
}


class LocationSettings(StrictModel):
    geo_mode: Literal["proxy", "manual", "system"] = "system"
    locale: str | None = None
    timezone: str | None = None
    webrtc_mode: Literal["proxy", "direct", "disabled"] = "direct"
    geolocation_mode: Literal["proxy", "manual", "ask", "block"] = "ask"
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy: float | None = Field(default=None, gt=0, le=100000)

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: str | None) -> str | None:
        if value is not None and not _LOCALE_RE.fullmatch(value):
            raise ValueError("locale must be a BCP 47-style language tag")
        return value

    @model_validator(mode="after")
    def validate_geolocation(self):
        coordinates = (self.latitude, self.longitude)
        if self.geolocation_mode == "manual" and any(value is None for value in coordinates):
            raise ValueError("manual geolocation requires latitude and longitude")
        if self.geolocation_mode != "manual" and any(value is not None for value in coordinates):
            raise ValueError("coordinates are allowed only for manual geolocation")
        if self.geolocation_mode != "manual" and self.accuracy is not None:
            raise ValueError("accuracy is allowed only for manual geolocation")
        return self


class WindowSettings(StrictModel):
    mode: Literal["maximized", "custom"] = "maximized"
    width: int | None = Field(default=None, ge=800, le=7680)
    height: int | None = Field(default=None, ge=600, le=4320)
    color_scheme: Literal["system", "light", "dark"] = "system"

    @model_validator(mode="after")
    def validate_dimensions(self):
        dimensions = (self.width, self.height)
        if self.mode == "custom" and any(value is None for value in dimensions):
            raise ValueError("custom window mode requires width and height")
        if self.mode == "maximized" and any(value is not None for value in dimensions):
            raise ValueError("maximized window mode does not accept dimensions")
        return self


class BehaviorSettings(StrictModel):
    humanize_enabled: bool = False
    humanize_preset: Literal["default", "careful"] = "default"
    clear_cache_before_launch: bool = False
    restore_previous_tabs: bool = True
    download_directory_mode: Literal["profile", "custom"] = "profile"
    custom_download_directory: str | None = Field(default=None, max_length=1024)
    permissions: dict[str, Literal["ask", "allow", "block"]] = Field(default_factory=dict)
    ignore_https_errors: bool = False
    hardware_concurrency_mode: Literal["automatic", "custom"] = "automatic"
    hardware_concurrency: int | None = Field(default=None, ge=2, le=64)
    gpu_mode: Literal["automatic", "custom_vendor"] = "automatic"
    gpu_vendor: str | None = Field(default=None, min_length=1, max_length=120)
    additional_args: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("additional_args")
    @classmethod
    def reject_manager_owned_args(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value.startswith("--") or any(character in value for character in "\r\n\0"):
                raise ValueError("Chromium arguments must be single --flag values")
            key = value.split("=", 1)[0].lower()
            if key in _MANAGER_ARG_KEYS:
                raise ValueError(f"{key} is owned by CloakBrowser Manager")
        return values

    @model_validator(mode="after")
    def validate_modes(self):
        if self.hardware_concurrency_mode == "custom" and self.hardware_concurrency is None:
            raise ValueError("custom hardware concurrency requires a value")
        if self.hardware_concurrency_mode == "automatic" and self.hardware_concurrency is not None:
            raise ValueError("hardware concurrency value requires custom mode")
        if self.gpu_mode == "custom_vendor" and self.gpu_vendor is None:
            raise ValueError("custom GPU mode requires a vendor")
        if self.gpu_mode == "automatic" and self.gpu_vendor is not None:
            raise ValueError("GPU vendor requires custom_vendor mode")
        if self.download_directory_mode == "custom" and not self.custom_download_directory:
            raise ValueError("custom download mode requires a directory")
        if self.download_directory_mode == "profile" and self.custom_download_directory is not None:
            raise ValueError("custom directory requires custom download mode")
        return self


class ProfileCreate(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    folder_id: str | None = None
    workflow_status_id: str | None = None
    tag_ids: list[str] = Field(default_factory=list, max_length=100)
    notes: str = Field(default="", max_length=4000)
    pinned: bool = False
    startup_urls: list[str] = Field(default_factory=list, max_length=20)
    fingerprint_seed: str | None = None
    fingerprint_preset: Literal["default", "consistent"] = "consistent"
    browser_version_mode: Literal["installed", "pinned"] = "installed"
    browser_version: str | None = None
    user_agent_mode: Literal["automatic", "custom"] = "automatic"
    custom_user_agent: str | None = Field(default=None, min_length=20, max_length=512)
    location: LocationSettings = Field(default_factory=LocationSettings)
    window: WindowSettings = Field(default_factory=WindowSettings)
    behavior: BehaviorSettings = Field(default_factory=BehaviorSettings)
    proxy_id: str | None = None
    test_proxy_before_launch: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value

    @field_validator("fingerprint_seed")
    @classmethod
    def validate_seed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.isascii() or not value.isdecimal():
            raise ValueError("fingerprint seed must be unsigned decimal text")
        number = int(value)
        if number < 0 or number > 2**64 - 1:
            raise ValueError("fingerprint seed must fit an unsigned 64-bit integer")
        return str(number)

    @field_validator("startup_urls")
    @classmethod
    def validate_startup_urls(cls, values: list[str]) -> list[str]:
        for value in values:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https", "chrome-extension"}:
                raise ValueError("unsupported startup URL scheme")
            if not parsed.netloc:
                raise ValueError("startup URL requires a host or extension ID")
            if parsed.username or parsed.password:
                raise ValueError("startup URLs cannot contain credentials")
        return values

    @model_validator(mode="after")
    def validate_identity_modes(self):
        if self.browser_version_mode == "pinned":
            if self.browser_version is None or not _VERSION_RE.fullmatch(self.browser_version):
                raise ValueError("pinned browser mode requires a full numeric version")
        elif self.browser_version is not None:
            raise ValueError("browser version requires pinned mode")
        if self.user_agent_mode == "custom" and self.custom_user_agent is None:
            raise ValueError("custom user-agent mode requires a value")
        if self.user_agent_mode == "automatic" and self.custom_user_agent is not None:
            raise ValueError("custom user agent requires custom mode")
        return self


class ProfilePatch(ProfileCreate):
    name: str | None = Field(default=None, min_length=1, max_length=80)


class ProfileRead(ProfileCreate):
    id: str
    fingerprint_seed: str
    fingerprint_revision: int
    fingerprint_config_hash: str
    runtime_state: Literal[
        "queued", "stopped", "starting", "running", "stopping", "crashed", "detached"
    ] = "stopped"
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime | None = None
    total_runtime_seconds: int = 0
    deleted_at: datetime | None = None


class ProfilePage(Page[ProfileRead]):
    pass


class BulkProfileRequest(StrictModel):
    action: Literal["trash", "restore", "pin", "unpin", "move_folder", "set_status"]
    ids: list[str] = Field(min_length=1, max_length=100)
    folder_id: str | None = None
    workflow_status_id: str | None = None

    @model_validator(mode="after")
    def validate_action_value(self):
        if self.action == "move_folder" and self.folder_id is None:
            raise ValueError("move_folder requires folder_id")
        if self.action == "set_status" and self.workflow_status_id is None:
            raise ValueError("set_status requires workflow_status_id")
        return self


class BulkProfileResult(StrictModel):
    updated_ids: list[str]
    count: int
