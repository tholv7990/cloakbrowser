from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from pydantic import Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ...models import ProfileLogEntry
from ...schemas.common import Page


MAX_PROFILE_LOG_ENTRIES = 2_000
MAX_PROFILE_LOG_PAGE_SIZE = 200
_LEVELS = frozenset({"debug", "info", "warning", "error"})
_SANITIZE_RE = re.compile(
    r"""
    (?P<credential_url>\b(?:https?|socks5h?)://[^\s/@:]+:[^\s/@]+@[^\s]+)
    |(?P<license>\bcb_[A-Za-z0-9_-]+\b)
    |(?P<token>\b(?:cookie|set-cookie|session(?:[_-]?(?:id|token))?|token|authorization)\b\s*[:=]\s*[^\s;,\r\n]+)
    |(?P<absolute_path>(?:[A-Za-z]:[\\/]|(?<![:\w])/)[^\s\"'<>;,)]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)


class ProfileLogPage(Page[dict[str, Any]]):
    page_size: int = Field(ge=1, le=MAX_PROFILE_LOG_PAGE_SIZE)


def _is_allowed_profile_path(value: str, profile_root: Path, profile_id: str) -> bool:
    try:
        value_path = Path(value).resolve(strict=False)
        allowed_root = (profile_root / profile_id).resolve(strict=False)
        return value_path.is_relative_to(allowed_root)
    except (OSError, ValueError):
        return False


def sanitize_profile_log_message(message: str, *, profile_id: str, profile_root: Path) -> str:
    """Remove secrets and paths outside the manager-owned directory for a profile."""

    def replace(match: re.Match[str]) -> str:
        if match.lastgroup == "credential_url":
            return "[REDACTED_URL]"
        if match.lastgroup == "license":
            return "[REDACTED_LICENSE]"
        if match.lastgroup == "token":
            return "[REDACTED_TOKEN]"
        path = match.group("absolute_path")
        if path is not None and _is_allowed_profile_path(path, profile_root, profile_id):
            return path
        return "[REDACTED_PATH]"

    return _SANITIZE_RE.sub(replace, message)


def append_profile_log(
    session: Session,
    profile_id: str,
    level: str,
    event: str,
    message: str,
    *,
    profile_root: Path,
) -> ProfileLogEntry:
    if level not in _LEVELS:
        raise ValueError("profile log level is unsupported")
    if not event or len(event) > 80:
        raise ValueError("profile log event must contain at most 80 characters")
    if len(message) > 4000:
        raise ValueError("profile log message must contain at most 4000 characters")

    entry = ProfileLogEntry(
        profile_id=profile_id,
        level=level,
        event=event,
        message=sanitize_profile_log_message(
            message, profile_id=profile_id, profile_root=Path(profile_root)
        ),
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
