from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

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


class FolderRead(CatalogNameMixin):
    id: str
    position: int
    created_at: datetime
    updated_at: datetime


class TagCreate(CatalogNameMixin):
    color: str = Field(default="#64748B", pattern=r"^#[0-9A-Fa-f]{6}$")


class TagRead(TagCreate):
    id: str
    created_at: datetime
    updated_at: datetime


class WorkflowStatusCreate(TagCreate):
    pass


class WorkflowStatusRead(WorkflowStatusCreate):
    id: str
    position: int
    created_at: datetime
    updated_at: datetime
