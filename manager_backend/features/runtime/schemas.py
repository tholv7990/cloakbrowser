from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


RuntimeState = Literal[
    "queued", "starting", "running", "stopping", "stopped", "crashed", "detached"
]


class RuntimeRead(BaseModel):
    id: str
    profile_id: str
    state: RuntimeState
    last_message: str
    started_at: datetime | None
    stopped_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RuntimePage(BaseModel):
    items: list[RuntimeRead]
    total: int


class WorkAreaRead(BaseModel):
    x: int
    y: int
    width: int
    height: int


class MonitorRead(BaseModel):
    id: str
    label: str
    width: int
    height: int
    work_area: WorkAreaRead
    is_primary: bool


class MonitorsResponse(BaseModel):
    monitors: list[MonitorRead]


class ArrangeRequest(BaseModel):
    profile_ids: list[str]
    monitor_id: str
    layout: Literal["grid", "cascade"]


class ArrangeResultRead(BaseModel):
    profile_id: str
    ok: bool
    error: str | None = None


class ArrangeResponse(BaseModel):
    results: list[ArrangeResultRead]


class SyncStartRequest(BaseModel):
    control_profile_id: str
    follower_profile_ids: list[str]


class SyncStatusResponse(BaseModel):
    active: bool
    control_profile_id: str | None = None
    follower_profile_ids: list[str] = []


class BroadcastRequest(BaseModel):
    """Open a URL, or type text, on several profiles at once. Exactly one of the two."""

    profile_ids: list[str]
    url: str | None = None
    text: str | None = Field(default=None, max_length=10_000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip()
        # http(s) only: javascript:/file:/data: would execute or read locally.
        if not candidate.lower().startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return candidate

    @model_validator(mode="after")
    def exactly_one_payload(self):
        if bool(self.url) == bool(self.text):
            raise ValueError("provide either a url or text, not both")
        return self


class BroadcastResponse(BaseModel):
    results: list[ArrangeResultRead]
