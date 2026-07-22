from __future__ import annotations

from collections.abc import Callable
from math import ceil
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ...errors import ManagerError
from ...models import DiagnosticRun, Profile, utc_now


DIAGNOSTIC_KINDS = frozenset(
    {
        "direct_google_control",
        "pixelscan",
        "iphey",
        "cloudflare",
        "google_search",
    }
)
DIAGNOSTIC_STATUSES = frozenset(
    {"queued", "running", "passed", "warning", "failed", "cancelled"}
)
ACTIVE_STATUSES = frozenset({"queued", "running"})
TERMINAL_STATUSES = frozenset({"passed", "warning", "failed", "cancelled"})

TARGET_URLS = {
    "direct_google_control": "https://www.google.com/search?q=CloakBrowser+diagnostic",
    "pixelscan": "https://pixelscan.net/",
    "iphey": "https://iphey.com/",
    "cloudflare": "https://challenge.cloudflare.com/turnstile/v0/generic/",
    "google_search": "https://www.google.com/search?q=CloakBrowser+browser+diagnostic",
}

_TRANSITIONS = {
    "queued": frozenset({"running", "failed", "cancelled"}),
    "running": TERMINAL_STATUSES,
    "passed": frozenset(),
    "warning": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


def _not_found() -> ManagerError:
    return ManagerError(
        "diagnostic_not_found", "The requested diagnostic was not found.", 404
    )


def _profile_not_found() -> ManagerError:
    return ManagerError("profile_not_found", "The requested profile was not found.", 404)


def _active_conflict() -> ManagerError:
    return ManagerError(
        "diagnostic_already_active",
        "A diagnostic is already active for this profile.",
        409,
    )


def _safe_artifact_path(
    value: str | None, data_root: Path, run_id: str
) -> str | None:
    if value is None:
        return None
    try:
        candidate = Path(value).resolve()
        owned_root = (data_root / "diagnostics" / run_id).resolve()
        if not candidate.is_relative_to(owned_root):
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return str(candidate)


def diagnostic_to_dict(run: DiagnosticRun, data_root: Path) -> dict:
    return {
        "id": run.id,
        "profile_id": run.profile_id,
        "kind": run.kind,
        "status": run.status,
        "target_url": run.target_url,
        "requested_at": run.requested_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "progress": max(0, min(100, int(run.progress))),
        "summary": run.summary,
        "findings": run.findings if isinstance(run.findings, dict) else {},
        "screenshot_path": _safe_artifact_path(
            run.screenshot_path, data_root, run.id
        ),
        "report_path": _safe_artifact_path(run.report_path, data_root, run.id),
        "error_code": run.error_code,
        "error_message": run.error_message,
    }


def get_diagnostic(session, diagnostic_id: str) -> DiagnosticRun:
    run = session.get(DiagnosticRun, diagnostic_id)
    if run is None:
        raise _not_found()
    return run


def list_diagnostics(
    session,
    *,
    profile_id: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[DiagnosticRun], int, int]:
    filters = []
    if profile_id is not None:
        filters.append(DiagnosticRun.profile_id == profile_id)
    if kind is not None:
        filters.append(DiagnosticRun.kind == kind)
    if status is not None:
        filters.append(DiagnosticRun.status == status)
    total = int(
        session.scalar(select(func.count(DiagnosticRun.id)).where(*filters)) or 0
    )
    items = list(
        session.scalars(
            select(DiagnosticRun)
            .where(*filters)
            .order_by(DiagnosticRun.requested_at.desc(), DiagnosticRun.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return items, total, ceil(total / page_size) if total else 0


class DiagnosticManager:
    def __init__(
        self,
        session_factory,
        *,
        scheduler: Callable[[str], None] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._scheduler = scheduler or (lambda _run_id: None)

    def set_scheduler(self, scheduler: Callable[[str], None]) -> None:
        self._scheduler = scheduler

    def create(self, kind: str, profile_id: str | None) -> DiagnosticRun:
        if kind not in DIAGNOSTIC_KINDS:
            raise ManagerError(
                "invalid_diagnostic_kind", "The diagnostic kind is not supported.", 422
            )
        if kind == "direct_google_control":
            if profile_id is not None:
                raise ManagerError(
                    "invalid_diagnostic_profile",
                    "The direct control does not use a profile.",
                    422,
                )
        elif profile_id is None:
            raise ManagerError(
                "diagnostic_profile_required",
                "This diagnostic requires a profile.",
                422,
            )

        with self._session_factory() as session:
            if profile_id is not None:
                profile = session.get(Profile, profile_id)
                if profile is None or profile.deleted_at is not None:
                    raise _profile_not_found()
                active = session.scalar(
                    select(DiagnosticRun.id).where(
                        DiagnosticRun.profile_id == profile_id,
                        DiagnosticRun.status.in_(ACTIVE_STATUSES),
                    )
                )
                if active is not None:
                    raise _active_conflict()
            run = DiagnosticRun(
                profile_id=profile_id,
                kind=kind,
                status="queued",
                target_url=TARGET_URLS[kind],
                progress=0,
                findings={},
            )
            session.add(run)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if profile_id is not None:
                    raise _active_conflict() from None
                raise
            session.refresh(run)

        self._scheduler(run.id)
        return run

    def cancel(self, diagnostic_id: str) -> DiagnosticRun:
        return self.transition(diagnostic_id, "cancelled")

    def transition(self, diagnostic_id: str, status: str) -> DiagnosticRun:
        if status not in DIAGNOSTIC_STATUSES:
            raise ManagerError(
                "invalid_diagnostic_status", "The diagnostic status is not supported.", 422
            )
        with self._session_factory() as session:
            run = get_diagnostic(session, diagnostic_id)
            if status not in _TRANSITIONS[run.status]:
                code = (
                    "diagnostic_not_active"
                    if status == "cancelled"
                    else "invalid_diagnostic_transition"
                )
                message = (
                    "The diagnostic is no longer active."
                    if status == "cancelled"
                    else "The requested diagnostic state transition is not allowed."
                )
                raise ManagerError(code, message, 409)
            now = utc_now()
            run.status = status
            if status == "running" and run.started_at is None:
                run.started_at = now
            if status in TERMINAL_STATUSES:
                run.completed_at = now
                run.progress = 100
            session.commit()
            session.refresh(run)
            return run

    def update_progress(self, diagnostic_id: str, progress: int) -> DiagnosticRun:
        with self._session_factory() as session:
            run = get_diagnostic(session, diagnostic_id)
            if run.status not in ACTIVE_STATUSES:
                raise ManagerError(
                    "diagnostic_not_active", "The diagnostic is no longer active.", 409
                )
            run.progress = max(0, min(100, int(progress)))
            session.commit()
            session.refresh(run)
            return run

    def recover_orphans(self) -> int:
        with self._session_factory() as session:
            runs = list(
                session.scalars(
                    select(DiagnosticRun).where(
                        DiagnosticRun.status.in_(ACTIVE_STATUSES)
                    )
                )
            )
            now = utc_now()
            for run in runs:
                run.status = "failed"
                run.progress = 100
                run.completed_at = now
                run.error_code = "manager_restarted"
                run.error_message = (
                    "The manager restarted before the diagnostic completed."
                )
            session.commit()
            return len(runs)
