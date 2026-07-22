from __future__ import annotations

from datetime import datetime

from ...schemas.common import StrictModel


class SystemResources(StrictModel):
    cpu_percent: float
    memory_percent: float
    memory_used_bytes: int
    memory_total_bytes: int
    logical_cpus: int


class ProcessGroupResources(StrictModel):
    cpu_percent: float
    memory_bytes: int
    process_count: int


class BrowsersResources(ProcessGroupResources):
    profiles_running: int


class ProfileResourceRow(ProcessGroupResources):
    profile_id: str
    profile_name: str
    runtime_state: str


class ResourceSnapshot(StrictModel):
    generated_at: datetime
    system: SystemResources
    backend: ProcessGroupResources
    browsers: BrowsersResources
    profiles: list[ProfileResourceRow]


class RuntimeSessionRecord(StrictModel):
    id: str
    profile_id: str
    profile_name: str
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    startup_ms: int | None
    exit_reason: str | None
