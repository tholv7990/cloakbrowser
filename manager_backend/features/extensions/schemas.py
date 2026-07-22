from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import (
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from ...schemas.common import StrictModel


class ExtensionStrictModel(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)


CanonicalUuid = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    ),
]


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
    extension_ids: list[CanonicalUuid] = Field(max_length=100)

    @field_validator("extension_ids")
    @classmethod
    def reject_duplicates(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("extension_ids must not contain duplicates")
        return values


class ProfileExtensionAssignmentRead(ExtensionStrictModel):
    extension_ids: list[CanonicalUuid]


class ExtensionRead(ExtensionStrictModel):
    id: CanonicalUuid
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
