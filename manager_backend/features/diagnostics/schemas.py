from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from ...schemas.common import Page, StrictModel


DiagnosticKind = Literal[
    "direct_google_control",
    "pixelscan",
    "iphey",
    "cloudflare",
    "google_search",
]
DiagnosticStatus = Literal[
    "queued", "running", "passed", "warning", "failed", "cancelled"
]


class ProfileDiagnosticRequest(StrictModel):
    profile_id: str = Field(min_length=1, max_length=36)


class DiagnosticRead(StrictModel):
    id: str
    profile_id: str | None
    kind: DiagnosticKind
    status: DiagnosticStatus
    target_url: str
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    progress: int = Field(ge=0, le=100)
    summary: str | None
    findings: dict[str, Any]
    screenshot_path: str | None
    report_path: str | None
    error_code: str | None
    error_message: str | None


class DiagnosticPage(Page[DiagnosticRead]):
    pass
