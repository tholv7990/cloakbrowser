"""Append-only audit trail helper. Records non-secret events only (ids, actions,
plan ids, counts) — never a key, token, or password."""

from __future__ import annotations

from typing import Any

from . import models


def record(
    session,
    *,
    actor: str,
    action: str,
    subject_type: str,
    subject_id: str,
    data: dict[str, Any] | None = None,
) -> models.AuditEvent:
    event = models.AuditEvent(
        actor=actor,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        data=data or {},
    )
    session.add(event)
    return event
