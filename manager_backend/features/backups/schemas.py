from __future__ import annotations

from datetime import datetime

from ...schemas.common import StrictModel


class BackupArchiveRead(StrictModel):
    id: str
    created_at: datetime
    size_bytes: int
    automatic: bool
    verified: bool
    contents: list[str]
