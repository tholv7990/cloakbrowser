from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from ...schemas.common import StrictModel


MediaKind = Literal["camera", "microphone", "screen"]


class MediaSettingsRead(StrictModel):
    enabled: bool


class MediaSettingsPatch(StrictModel):
    enabled: bool


class MediaAssetRead(StrictModel):
    id: str
    name: str
    kind: MediaKind
    format: str
    size_bytes: int
    assigned_profile_count: int
    created_at: datetime


class MediaAssetCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    kind: MediaKind
    format: str = Field(min_length=1, max_length=80)


class MediaAssignmentsWrite(StrictModel):
    profile_ids: list[str] = Field(default_factory=list)
