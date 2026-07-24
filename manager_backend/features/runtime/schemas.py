from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


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
