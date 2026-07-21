from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ...config import ManagerSettings
from ...models import ProfileLogEntry
from ...schemas.common import Page


MAX_PROFILE_LOG_ENTRIES = 2_000
MAX_PROFILE_LOG_PAGE_SIZE = 200
_LEVELS = frozenset({"debug", "info", "warning", "error"})
_EVENT_TEMPLATES = {
    "runtime.start_requested": "Runtime start requested.",
    "runtime.preflight_failed": "Runtime preflight failed.",
    "runtime.process_started": "Runtime process started.",
    "runtime.ready": "Runtime ready.",
    "runtime.stop_requested": "Runtime stop requested.",
    "runtime.exited": "Runtime exited.",
    "runtime.crashed": "Runtime crashed.",
    "runtime.reconciled": "Runtime reconciled.",
}
_EVENT_FIELDS = {
    "runtime.process_started": frozenset({"profile_path"}),
    "runtime.exited": frozenset({"exit_code"}),
}


class ProfileLogPage(Page[dict[str, Any]]):
    page_size: int = Field(ge=1, le=MAX_PROFILE_LOG_PAGE_SIZE)


def _profile_path_value(value: object, settings: ManagerSettings, profile_id: str) -> str:
    if not isinstance(value, str) or len(value) > 1024:
        raise ValueError("profile_path must be a bounded string")
    try:
        value_path = Path(value).resolve(strict=False)
        allowed_root = (settings.data_root / "profiles" / profile_id).resolve(strict=False)
        allowed_paths = {allowed_root, allowed_root / "user-data"}
        return str(value_path) if value_path in allowed_paths else "[REDACTED_PATH]"
    except (OSError, ValueError):
        return "[REDACTED_PATH]"


def _message_for_event(
    event: str,
    fields: Mapping[str, object] | None,
    *,
    profile_id: str,
    settings: ManagerSettings,
) -> str:
    template = _EVENT_TEMPLATES.get(event)
    if template is None:
        raise ValueError("profile log event is unsupported")
    if fields is not None and not isinstance(fields, Mapping):
        raise ValueError("profile log fields must be a mapping")
    safe_fields = dict(fields or {})
    allowed_fields = _EVENT_FIELDS.get(event, frozenset())
    if set(safe_fields) - allowed_fields:
        raise ValueError("profile log fields are unsupported for this event")
    if event == "runtime.process_started" and "profile_path" in safe_fields:
        return f"Runtime process started at {_profile_path_value(safe_fields['profile_path'], settings, profile_id)}."
    if event == "runtime.exited" and "exit_code" in safe_fields:
        exit_code = safe_fields["exit_code"]
        if isinstance(exit_code, bool) or not isinstance(exit_code, int) or not -1 <= exit_code <= 255:
            raise ValueError("exit_code must be an integer between -1 and 255")
        return f"Runtime exited with code {exit_code}."
    return template


def append_profile_log(
    session: Session,
    profile_id: str,
    level: str,
    event: str,
    *,
    fields: Mapping[str, object] | None = None,
    settings: ManagerSettings,
) -> ProfileLogEntry:
    if level not in _LEVELS:
        raise ValueError("profile log level is unsupported")
    message = _message_for_event(event, fields, profile_id=profile_id, settings=settings)

    entry = ProfileLogEntry(
        profile_id=profile_id,
        level=level,
        event=event,
        message=message,
    )
    session.add(entry)
    session.flush()
    stale_ids = (
        select(ProfileLogEntry.id)
        .where(ProfileLogEntry.profile_id == profile_id)
        .order_by(ProfileLogEntry.created_at.desc(), ProfileLogEntry.id.desc())
        .offset(MAX_PROFILE_LOG_ENTRIES)
    )
    session.execute(
        delete(ProfileLogEntry).where(
            ProfileLogEntry.profile_id == profile_id,
            ProfileLogEntry.id.in_(stale_ids),
        )
    )
    session.commit()
    session.refresh(entry)
    return entry


def list_profile_logs(
    session: Session,
    profile_id: str,
    *,
    page: int = 1,
    page_size: int = 50,
) -> Page[dict[str, Any]]:
    if page < 1:
        raise ValueError("profile log page must be at least 1")
    if not 1 <= page_size <= MAX_PROFILE_LOG_PAGE_SIZE:
        raise ValueError("profile log page size must be between 1 and 200")

    statement = select(ProfileLogEntry).where(ProfileLogEntry.profile_id == profile_id)
    total = int(session.scalar(select(func.count(ProfileLogEntry.id)).where(ProfileLogEntry.profile_id == profile_id)) or 0)
    entries = list(
        session.scalars(
            statement.order_by(ProfileLogEntry.created_at.desc(), ProfileLogEntry.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return ProfileLogPage(
        items=[
            {
                "id": entry.id,
                "profile_id": entry.profile_id,
                "created_at": entry.created_at,
                "level": entry.level,
                "event": entry.event,
                "message": entry.message,
            }
            for entry in entries
        ],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )
