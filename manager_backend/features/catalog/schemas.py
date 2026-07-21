from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from ...schemas.common import StrictModel


class CatalogNameMixin(StrictModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class FolderCreate(CatalogNameMixin):
    pass


class FolderPatch(CatalogNameMixin):
    pass


class FolderRead(CatalogNameMixin):
    id: str
    position: int
    created_at: datetime
    updated_at: datetime
    profile_count: int
    running_count: int


class TagCreate(CatalogNameMixin):
    color: str = Field(default="#64748B", pattern=r"^#[0-9A-Fa-f]{6}$")


class TagPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if self.name is None and self.color is None:
            raise ValueError("at least one field is required")
        return self


class TagRead(TagCreate):
    id: str
    created_at: datetime
    updated_at: datetime


class WorkflowStatusCreate(TagCreate):
    pass


class WorkflowStatusPatch(TagPatch):
    pass


class WorkflowStatusRead(WorkflowStatusCreate):
    id: str
    position: int
    created_at: datetime
    updated_at: datetime


class ReorderRequest(StrictModel):
    ids: list[str] = Field(min_length=1, max_length=500)
