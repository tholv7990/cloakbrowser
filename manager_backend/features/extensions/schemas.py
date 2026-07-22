from __future__ import annotations

from datetime import datetime

from pydantic import ConfigDict, Field, model_validator

from ...schemas.common import StrictModel


class ExtensionStrictModel(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ExtensionRegister(ExtensionStrictModel):
    directory: str = Field(min_length=1, max_length=2048)


class ExtensionPatch(ExtensionStrictModel):
    enabled: bool | None = None
    refresh: bool = False

    @model_validator(mode="after")
    def require_operation(self):
        if self.enabled is None and not self.refresh:
            raise ValueError("enabled or refresh is required")
        return self


class ProfileExtensionAssignment(ExtensionStrictModel):
    extension_ids: list[str] = Field(max_length=100)


class ProfileExtensionAssignmentRead(ExtensionStrictModel):
    extension_ids: list[str]


class ExtensionRead(ExtensionStrictModel):
    id: str
    directory: str
    name: str
    version: str
    description: str
    manifest_version: int
    permissions: list[str]
    enabled: bool
    manifest_hash: str
    created_at: datetime
    updated_at: datetime
