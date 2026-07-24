from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from ...schemas.common import Page, StrictModel


_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){3,4}$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


def _validate_custom_user_agent(value: str | None) -> str | None:
    # F-008: a custom UA that doesn't declare the Windows platform contradicts the
    # Windows-only persona (and the engine-derived Client Hints).
    if value is not None and "Windows NT" not in value:
        raise ValueError("custom user agent must match the Windows platform")
    return value


def _pinned_version_older_than_bundled(version: str | None) -> bool:
    # F-011 (partial): a pinned build older than the bundled free one can never resolve.
    # Rejecting unresolvable *newer* pins needs the cloud version list (not done here).
    if version is None:
        return False
    from cloakbrowser.config import get_chromium_version

    try:
        return int(version.split(".")[0]) < int(get_chromium_version().split(".")[0])
    except (ValueError, IndexError):
        return False


class LocationSettings(StrictModel):
    # Default to deriving geo from the proxy: with no proxy this falls back to the
    # host timezone at launch, but a proxied profile then matches its exit IP
    # instead of leaking the host timezone (the "timezone spoofed" flag).
    geo_mode: Literal["proxy", "manual", "system"] = "proxy"
    locale: str | None = None
    timezone: str | None = None
    # "disabled" retired (F-001): the launcher never enforced it, so offering it
    # promised a WebRTC-off behavior the engine does not deliver. proxy | direct only.
    webrtc_mode: Literal["proxy", "direct"] = "proxy"
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


# The consistent preset spoofs a 1920x1080 screen (and the free binary clamps to
# it); a custom window must not exceed that, or outerWidth/innerWidth > screen.width
# — an impossible, detectable geometry (F-015).
_SPOOFED_SCREEN = (1920, 1080)


class WindowSettings(StrictModel):
    mode: Literal["maximized", "custom"] = "maximized"
    width: int | None = Field(default=None, ge=800, le=_SPOOFED_SCREEN[0])
    height: int | None = Field(default=None, ge=600, le=_SPOOFED_SCREEN[1])
    # color_scheme retired (F-006): it was stored but never applied at launch.

    @model_validator(mode="after")
    def validate_dimensions(self):
        dimensions = (self.width, self.height)
        if self.mode == "custom" and any(value is None for value in dimensions):
            raise ValueError("custom window mode requires width and height")
        if self.mode == "maximized" and any(value is not None for value in dimensions):
            raise ValueError("maximized window mode does not accept dimensions")
        return self


class BehaviorSettings(StrictModel):
    # Only permissions remain: they are applied at launch (F-005). The former
    # humanize / hardware-concurrency / GPU / downloads / additional-args / cache /
    # https / restore-tabs fields were stored but never reached the browser (F-006)
    # and were retired; two of them (hardware/GPU) had also polluted the config hash.
    permissions: dict[str, Literal["ask", "allow", "block"]] = Field(default_factory=dict)


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

    @field_validator("custom_user_agent")
    @classmethod
    def validate_custom_user_agent(cls, value: str | None) -> str | None:
        return _validate_custom_user_agent(value)

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
            if _pinned_version_older_than_bundled(self.browser_version):
                raise ValueError("pinned browser version cannot be older than the bundled build")
        elif self.browser_version is not None:
            raise ValueError("browser version requires pinned mode")
        if self.user_agent_mode == "custom" and self.custom_user_agent is None:
            raise ValueError("custom user-agent mode requires a value")
        if self.user_agent_mode == "automatic" and self.custom_user_agent is not None:
            raise ValueError("custom user agent requires custom mode")
        return self


class ProfilePatch(StrictModel):
    expected_updated_at: datetime
    name: str = Field(default=None, min_length=1, max_length=80)  # type: ignore[assignment]
    folder_id: str | None = None
    workflow_status_id: str | None = None
    tag_ids: list[str] = Field(default=None, max_length=100)  # type: ignore[assignment]
    notes: str = Field(default=None, max_length=4000)  # type: ignore[assignment]
    pinned: bool = None  # type: ignore[assignment]
    startup_urls: list[str] = Field(default=None, max_length=20)  # type: ignore[assignment]
    fingerprint_preset: Literal["default", "consistent"] = None  # type: ignore[assignment]
    browser_version_mode: Literal["installed", "pinned"] = None  # type: ignore[assignment]
    browser_version: str | None = None
    user_agent_mode: Literal["automatic", "custom"] = None  # type: ignore[assignment]
    custom_user_agent: str | None = Field(default=None, min_length=20, max_length=512)
    location: LocationSettings = None  # type: ignore[assignment]
    window: WindowSettings = None  # type: ignore[assignment]
    behavior: BehaviorSettings = None  # type: ignore[assignment]
    proxy_id: str | None = None
    test_proxy_before_launch: bool = None  # type: ignore[assignment]

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value

    @field_validator("browser_version")
    @classmethod
    def validate_browser_version(cls, value: str | None) -> str | None:
        if value is not None and not _VERSION_RE.fullmatch(value):
            raise ValueError("browser version must be a full numeric version")
        return value

    @field_validator("custom_user_agent")
    @classmethod
    def validate_custom_user_agent(cls, value: str | None) -> str | None:
        return _validate_custom_user_agent(value)

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


class ProfileRead(ProfileCreate):
    id: str
    profile_directory: str
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


class ProfileDirectoryOpen(StrictModel):
    profile_directory: str


class ProfileLogRead(StrictModel):
    id: str
    profile_id: str
    created_at: datetime
    level: Literal["debug", "info", "warning", "error"]
    event: Literal[
        "runtime.start_requested",
        "runtime.preflight_failed",
        "runtime.process_started",
        "runtime.ready",
        "runtime.stop_requested",
        "runtime.exited",
        "runtime.crashed",
        "runtime.reconciled",
    ]
    message: str


class ProfileLogPage(Page[ProfileLogRead]):
    page_size: int = Field(ge=1, le=200)


class BulkProfileRequest(StrictModel):
    action: Literal[
        "trash", "restore", "pin", "unpin", "move_folder", "set_status", "add_tag", "remove_tag"
    ]
    ids: list[str] = Field(min_length=1, max_length=100)
    folder_id: str | None = None
    workflow_status_id: str | None = None
    tag_id: str | None = None

    @model_validator(mode="after")
    def validate_action_value(self):
        if self.action == "move_folder" and self.folder_id is None:
            raise ValueError("move_folder requires folder_id")
        if self.action == "set_status" and self.workflow_status_id is None:
            raise ValueError("set_status requires workflow_status_id")
        if self.action in ("add_tag", "remove_tag") and self.tag_id is None:
            raise ValueError(f"{self.action} requires tag_id")
        return self


class BulkProfileResult(StrictModel):
    updated_ids: list[str]
    count: int
