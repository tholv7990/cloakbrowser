from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints, field_validator, model_validator

from ...schemas.common import StrictModel
from ..profiles.schemas import LocationSettings, WindowSettings


PROFILE_EXPORT_FORMAT = "cloakbrowser-manager-profile"
PROFILE_EXPORT_VERSION = 1
MAX_PROFILE_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_PORTABLE_PERMISSIONS = 64
MAX_PORTABLE_PERMISSION_KEY_LENGTH = 80
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PortablePermissionKey = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_PORTABLE_PERMISSION_KEY_LENGTH),
]


def _normalized_name(value: str) -> str:
    return " ".join(value.split())


class PortableStrictModel(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PortableLocationSettings(LocationSettings):
    model_config = ConfigDict(extra="forbid", strict=True)


class PortableWindowSettings(WindowSettings):
    model_config = ConfigDict(extra="forbid", strict=True)


class PortableFolder(PortableStrictModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = _normalized_name(value)
        if not value:
            raise ValueError("name cannot be blank")
        return value


class PortableColoredCatalog(PortableStrictModel):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = _normalized_name(value)
        if not value:
            raise ValueError("name cannot be blank")
        return value

    @field_validator("color")
    @classmethod
    def canonical_color(cls, value: str) -> str:
        return value.upper()


class PortableBehaviorSettings(PortableStrictModel):
    humanize_enabled: bool = False
    humanize_preset: Literal["default", "careful"] = "default"
    clear_cache_before_launch: bool = False
    restore_previous_tabs: bool = True
    permissions: dict[PortablePermissionKey, Literal["ask", "allow", "block"]] = Field(
        default_factory=dict,
        max_length=MAX_PORTABLE_PERMISSIONS,
    )
    ignore_https_errors: bool = False
    hardware_concurrency_mode: Literal["automatic", "custom"] = "automatic"
    hardware_concurrency: int | None = Field(default=None, ge=2, le=64)
    gpu_mode: Literal["automatic", "custom_vendor"] = "automatic"
    gpu_vendor: str | None = Field(default=None, min_length=1, max_length=120)

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
        return self


class PortableProxy(PortableStrictModel):
    scheme: Literal["direct", "http", "https", "socks5", "socks5h"]
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)

    @model_validator(mode="after")
    def validate_endpoint(self):
        if self.scheme == "direct" and (self.host is not None or self.port is not None):
            raise ValueError("direct proxy metadata cannot contain an endpoint")
        if self.scheme != "direct" and (self.host is None or self.port is None):
            raise ValueError("proxy metadata requires host and port")
        return self


class PortableExtension(PortableStrictModel):
    name: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=64)
    manifest_version: Literal[2, 3]
    manifest_hash: str

    @field_validator("manifest_hash")
    @classmethod
    def validate_manifest_hash(cls, value: str) -> str:
        value = value.lower()
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("manifest_hash must be a SHA-256 hex digest")
        return value


class PortableProfile(PortableStrictModel):
    name: str = Field(min_length=1, max_length=80)
    folder: PortableFolder | None = None
    workflow_status: PortableColoredCatalog | None = None
    tags: list[PortableColoredCatalog] = Field(default_factory=list, max_length=100)
    notes: str = Field(default="", max_length=4000)
    pinned: bool = False
    startup_urls: list[str] = Field(default_factory=list, max_length=20)
    fingerprint_preset: Literal["default", "consistent"] = "consistent"
    browser_version_mode: Literal["installed", "pinned"] = "installed"
    browser_version: str | None = None
    user_agent_mode: Literal["automatic", "custom"] = "automatic"
    custom_user_agent: str | None = Field(default=None, min_length=20, max_length=512)
    location: PortableLocationSettings = Field(default_factory=PortableLocationSettings)
    window: PortableWindowSettings = Field(default_factory=PortableWindowSettings)
    behavior: PortableBehaviorSettings = Field(default_factory=PortableBehaviorSettings)
    proxy: PortableProxy | None = None
    test_proxy_before_launch: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_profile_settings(self):
        from ..profiles.schemas import ProfileCreate

        ProfileCreate(
            name=self.name,
            notes=self.notes,
            pinned=self.pinned,
            startup_urls=self.startup_urls,
            fingerprint_preset=self.fingerprint_preset,
            browser_version_mode=self.browser_version_mode,
            browser_version=self.browser_version,
            user_agent_mode=self.user_agent_mode,
            custom_user_agent=self.custom_user_agent,
            location=self.location.model_dump(mode="python"),
            window=self.window.model_dump(mode="python"),
            behavior={
                **self.behavior.model_dump(mode="python"),
                "download_directory_mode": "profile",
                "custom_download_directory": None,
                "additional_args": [],
            },
            test_proxy_before_launch=self.test_proxy_before_launch,
        )
        return self


class ProfileExportV1(PortableStrictModel):
    format: Literal["cloakbrowser-manager-profile"]
    version: Literal[1]
    exported_at: datetime
    profile: PortableProfile
    extensions: list[PortableExtension] = Field(default_factory=list, max_length=100)

    @field_validator("version", mode="before")
    @classmethod
    def require_exact_version_type(cls, value: object) -> object:
        if type(value) is not int or value != PROFILE_EXPORT_VERSION:
            raise ValueError("unsupported profile document version")
        return value

    @field_validator("exported_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("exported_at must include a timezone")
        return value


class ProfileImportWarning(PortableStrictModel):
    code: Literal[
        "proxy_assignment_skipped",
        "extension_missing",
        "extension_ambiguous",
        "chrome_extension_startup_url_skipped",
    ]
    message: str = Field(min_length=1, max_length=240)


class ProfileImportResult(PortableStrictModel):
    profile_id: str
    profile_name: str
    warnings: list[ProfileImportWarning] = Field(default_factory=list, max_length=102)


class CookieImportWarning(PortableStrictModel):
    index: int = Field(ge=0, le=9_999)
    code: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_]+$")


class CookieImportResult(PortableStrictModel):
    format: Literal["json", "playwright", "netscape"]
    imported_count: int = Field(ge=0, le=10_000)
    skipped_count: int = Field(ge=0, le=10_000)
    rejected_count: int = Field(ge=0, le=10_000)
    warnings: list[CookieImportWarning] = Field(default_factory=list, max_length=16)
