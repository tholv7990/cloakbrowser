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
