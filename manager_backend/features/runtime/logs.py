from __future__ import annotations

import math
import re
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
_EVENT_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_SANITIZE_RE = re.compile(
    r"""
    (?P<credential_url>\b(?:https?|socks5h?)://[^\s/@:]+:[^\s/@]+@[^\s]+)
    |(?P<license>\bcb_[A-Za-z0-9_-]+\b)
    |(?P<environment>\b(?:process\s+)?(?:environment|environ|env)\b(?:\s*[:=]\s*|\s+(?=[{\[]))(?:\{[^\r\n]*?\}|\[[^\r\n]*?\]|[^\r\n]+))
    |(?P<command>\b(?:command(?:\s+line)?|cmd|argv|arguments?)\b\s*[:=]\s*[^\r\n]+|(?:[A-Za-z]:[\\/][^\r\n]*?|(?:^|\s)[^\s\"']+)\.(?:exe|cmd|bat|ps1|sh|py)\b[^\r\n]*|--[A-Za-z][A-Za-z0-9_-]*(?:[=\s][^\r\n]*)?)
    |(?P<token>\b(?:cookie|set-cookie|session(?:[_-]?(?:id|token))?|token|authorization)\b\s*[:=]\s*[^\s;,\r\n]+)
    |(?P<credential>(?:[\"']?(?:password|passwd|pwd|api[_-]?key|secret|credential|auth|access[_-]?token|proxy[_-]?(?:user|password))[\"']?)\s*[:=]\s*[\"']?[^\s;,}\]\r\n]+)
    |(?P<absolute_path>(?:[A-Za-z]:[\\/]|\\\\|(?<![:\w])/)[^\s\"'<>;,)]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)


class ProfileLogPage(Page[dict[str, Any]]):
    page_size: int = Field(ge=1, le=MAX_PROFILE_LOG_PAGE_SIZE)


def _is_allowed_profile_path(value: str, settings: ManagerSettings, profile_id: str) -> bool:
    try:
        value_path = Path(value).resolve(strict=False)
        allowed_root = (settings.data_root / "profiles" / profile_id).resolve(strict=False)
        return value_path.is_relative_to(allowed_root)
    except (OSError, ValueError):
        return False


def sanitize_profile_log_message(
    message: str, *, profile_id: str, settings: ManagerSettings
) -> str:
    """Remove secrets and paths outside the manager-owned directory for a profile."""

    def replace(match: re.Match[str]) -> str:
        if match.lastgroup == "credential_url":
            return "[REDACTED_URL]"
        if match.lastgroup == "license":
            return "[REDACTED_LICENSE]"
        if match.lastgroup == "environment":
            return "[REDACTED_ENVIRONMENT]"
        if match.lastgroup == "command":
            return "[REDACTED_COMMAND]"
        if match.lastgroup == "token":
            return "[REDACTED_TOKEN]"
        if match.lastgroup == "credential":
            return "[REDACTED_CREDENTIAL]"
        path = match.group("absolute_path")
        if path is not None and _is_allowed_profile_path(path, settings, profile_id):
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
    settings: ManagerSettings,
) -> ProfileLogEntry:
    if level not in _LEVELS:
        raise ValueError("profile log level is unsupported")
    if len(event) > 80 or not _EVENT_RE.fullmatch(event):
        raise ValueError("profile log event must be a stable dotted identifier of at most 80 characters")
    if len(message) > 4000:
        raise ValueError("profile log message must contain at most 4000 characters")

    entry = ProfileLogEntry(
        profile_id=profile_id,
        level=level,
        event=event,
        message=sanitize_profile_log_message(
            message, profile_id=profile_id, settings=settings
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
