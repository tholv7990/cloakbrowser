from __future__ import annotations

from collections.abc import Callable
from math import ceil
from pathlib import Path
import sqlite3

from sqlalchemy import func, select, update as sql_update
from sqlalchemy.exc import IntegrityError, OperationalError

from ...errors import ManagerError
from ...models import DiagnosticRun, Profile, utc_now
from .schemas import DiagnosticResultUpdate, bounded_findings


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

SUMMARY_TEMPLATES = {
    "passed": "Diagnostic completed.",
    "warning": "Diagnostic completed with warnings.",
    "failed": "Diagnostic failed.",
    "cancelled": "Diagnostic cancelled.",
}
ERROR_MESSAGES = {
    "diagnostic_failed": "The diagnostic could not be completed.",
    "manager_restarted": "The manager restarted before the diagnostic completed.",
    "scheduler_unavailable": "The diagnostic could not be scheduled.",
    "browser_crashed": "The browser closed before the diagnostic completed.",
    "proxy_preflight_failed": "The assigned proxy is unavailable.",
    "network_error": "The diagnostic target could not be reached.",
    "timeout": "The diagnostic did not complete before its time limit.",
    "target_layout_changed": "The diagnostic target could not be read reliably.",
    "captcha_user_action_required": "The target requires user interaction.",
}
WARNING_ERROR_CODES = frozenset(
    {"target_layout_changed", "captcha_user_action_required"}
)
FAILURE_ERROR_CODES = frozenset(
    {
        "diagnostic_failed",
        "manager_restarted",
        "scheduler_unavailable",
        "browser_crashed",
        "proxy_preflight_failed",
        "network_error",
        "timeout",
        "target_layout_changed",
    }
)

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


def _write_conflict() -> ManagerError:
    return ManagerError(
        "diagnostic_conflict",
        "The diagnostic changed during this request. Try again.",
        409,
    )


def _safe_artifact_path(
    value: str | None, data_root: Path, run_id: str
) -> str | None:
    if value is None:
        return None
    try:
        resolved_data_root = Path(data_root).resolve()
        diagnostics_root = (resolved_data_root / "diagnostics").resolve()
        if not diagnostics_root.is_relative_to(resolved_data_root):
            return None
        owned_root = (diagnostics_root / run_id).resolve()
        if not owned_root.is_relative_to(diagnostics_root):
            return None
        candidate = Path(value).resolve()
        if not candidate.is_relative_to(owned_root):
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return str(candidate)


def _validated_artifact_path(
    value: str | None, data_root: Path, run_id: str
) -> str | None:
    safe = _safe_artifact_path(value, data_root, run_id)
    if value is not None and safe is None:
        raise ManagerError(
            "invalid_diagnostic_artifact",
            "The diagnostic artifact path is outside its owned directory.",
            422,
        )
    return safe


def _safe_error(status: str, value: object) -> tuple[str | None, str | None]:
    code = value if isinstance(value, str) else None
    if status == "warning":
        if code not in WARNING_ERROR_CODES:
            return None, None
    elif status == "failed":
        if code not in FAILURE_ERROR_CODES:
            code = "diagnostic_failed"
    else:
        return None, None
    return code, ERROR_MESSAGES.get(code) if code is not None else None


def diagnostic_to_dict(run: DiagnosticRun, data_root: Path) -> dict:
    error_code, error_message = _safe_error(run.status, run.error_code)
    return {
        "id": run.id,
        "profile_id": run.profile_id,
        "kind": run.kind,
        "status": run.status,
        "target_url": TARGET_URLS.get(run.kind, TARGET_URLS["direct_google_control"]),
        "requested_at": run.requested_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "progress": max(0, min(100, int(run.progress))),
        "summary": SUMMARY_TEMPLATES.get(run.status),
        "findings": bounded_findings(run.kind, run.findings),
        "screenshot_path": _safe_artifact_path(
            run.screenshot_path, data_root, run.id
        ),
        "report_path": _safe_artifact_path(run.report_path, data_root, run.id),
        "error_code": error_code,
        "error_message": error_message,
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


def _sqlite_constraint_codes(error: IntegrityError) -> tuple[int | None, int | None]:
    code = getattr(error.orig, "sqlite_errorcode", None)
    if not isinstance(code, int):
        return None, None
    return code, code & 0xFF


def _infer_data_root(session_factory) -> Path:
    database = session_factory.kw["bind"].url.database
    if not database:
        return Path.cwd()
    return Path(database).resolve().parent


class DiagnosticManager:
    def __init__(
        self,
        session_factory,
        *,
        scheduler: Callable[[str], None] | None = None,
        data_root: Path | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._scheduler = scheduler or (lambda _run_id: None)
        self._data_root = (data_root or _infer_data_root(session_factory)).resolve()

    def set_scheduler(self, scheduler: Callable[[str], None]) -> None:
        self._scheduler = scheduler

    def _reserve_create(self, session) -> None:
        try:
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        except OperationalError:
            session.rollback()
            raise _write_conflict() from None

    def _map_create_integrity(
        self, session, error: IntegrityError, profile_id: str | None
    ) -> None:
        code, base_code = _sqlite_constraint_codes(error)
        session.rollback()
        if profile_id is not None:
            profile = session.get(Profile, profile_id)
            if (
                profile is None
                or profile.deleted_at is not None
                or code == sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY
            ):
                raise _profile_not_found() from None
            active = session.scalar(
                select(DiagnosticRun.id).where(
                    DiagnosticRun.profile_id == profile_id,
                    DiagnosticRun.status.in_(ACTIVE_STATUSES),
                )
            )
            if active is not None and (
                code == sqlite3.SQLITE_CONSTRAINT_UNIQUE
                or base_code == sqlite3.SQLITE_CONSTRAINT
            ):
                raise _active_conflict() from None
        raise _write_conflict() from None

    def _current(self, diagnostic_id: str) -> DiagnosticRun:
        with self._session_factory() as session:
            return get_diagnostic(session, diagnostic_id)

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
            self._reserve_create(session)
            if profile_id is not None:
                profile = session.get(Profile, profile_id)
                if profile is None or profile.deleted_at is not None:
                    session.rollback()
                    raise _profile_not_found()
                active = session.scalar(
                    select(DiagnosticRun.id).where(
                        DiagnosticRun.profile_id == profile_id,
                        DiagnosticRun.status.in_(ACTIVE_STATUSES),
                    )
                )
                if active is not None:
                    session.rollback()
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
                session.flush()
                session.commit()
            except IntegrityError as error:
                self._map_create_integrity(session, error, profile_id)
            session.refresh(run)

        try:
            self._scheduler(run.id)
        except Exception:
            return self._mark_scheduler_unavailable(run.id)
        return self._current(run.id)

    def _cas_update(
        self,
        session,
        diagnostic_id: str,
        expected_status: str,
        values: dict,
        *,
        expected_progress: int | None = None,
    ) -> DiagnosticRun:
        predicates = [
            DiagnosticRun.id == diagnostic_id,
            DiagnosticRun.status == expected_status,
        ]
        if expected_progress is not None:
            predicates.append(DiagnosticRun.progress == expected_progress)
        try:
            result = session.execute(
                sql_update(DiagnosticRun)
                .where(*predicates)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
        except OperationalError:
            session.rollback()
            raise _write_conflict() from None
        if result.rowcount != 1:
            session.rollback()
            current = session.get(DiagnosticRun, diagnostic_id)
            if current is None:
                raise _not_found()
            if current.status == expected_status and current.status in ACTIVE_STATUSES:
                raise _write_conflict()
            raise ManagerError(
                "diagnostic_not_active", "The diagnostic is no longer active.", 409
            )
        session.commit()
        session.expire_all()
        current = session.get(DiagnosticRun, diagnostic_id)
        if current is None:
            raise _not_found()
        return current

    def _mark_scheduler_unavailable(self, diagnostic_id: str) -> DiagnosticRun:
        now = utc_now()
        with self._session_factory() as session:
            result = session.execute(
                sql_update(DiagnosticRun)
                .where(
                    DiagnosticRun.id == diagnostic_id,
                    DiagnosticRun.status.in_(ACTIVE_STATUSES),
                )
                .values(
                    status="failed",
                    progress=100,
                    completed_at=now,
                    summary=SUMMARY_TEMPLATES["failed"],
                    findings={},
                    error_code="scheduler_unavailable",
                    error_message=ERROR_MESSAGES["scheduler_unavailable"],
                )
                .execution_options(synchronize_session=False)
            )
            session.commit()
            session.expire_all()
            current = session.get(DiagnosticRun, diagnostic_id)
            if current is None:
                raise _not_found()
            if result.rowcount not in {0, 1}:
                raise _write_conflict()
            return current

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
            values: dict = {
                "status": status,
                "summary": SUMMARY_TEMPLATES.get(status),
                "error_code": None,
                "error_message": None,
            }
            if status == "running":
                values["started_at"] = run.started_at or now
            if status in TERMINAL_STATUSES:
                values.update(completed_at=now, progress=100)
            if status == "failed":
                values.update(
                    error_code="diagnostic_failed",
                    error_message=ERROR_MESSAGES["diagnostic_failed"],
                )
            return self._cas_update(session, diagnostic_id, run.status, values)

    def update_progress(self, diagnostic_id: str, progress: int) -> DiagnosticRun:
        with self._session_factory() as session:
            run = get_diagnostic(session, diagnostic_id)
            if run.status not in ACTIVE_STATUSES:
                raise ManagerError(
                    "diagnostic_not_active", "The diagnostic is no longer active.", 409
                )
            return self._cas_update(
                session,
                diagnostic_id,
                run.status,
                {"progress": max(0, min(100, int(progress)))},
                expected_progress=run.progress,
            )

    def store_result(
        self, diagnostic_id: str, result: DiagnosticResultUpdate
    ) -> DiagnosticRun:
        with self._session_factory() as session:
            run = get_diagnostic(session, diagnostic_id)
            if result.kind != run.kind:
                raise ManagerError(
                    "diagnostic_result_kind_mismatch",
                    "The result does not match the diagnostic kind.",
                    409,
                )
            if result.status not in _TRANSITIONS[run.status]:
                raise ManagerError(
                    "invalid_diagnostic_transition",
                    "The requested diagnostic state transition is not allowed.",
                    409,
                )
            error_code = result.error_code
            if result.status == "failed" and error_code is None:
                error_code = "diagnostic_failed"
            safe_code, safe_message = _safe_error(result.status, error_code)
            values = {
                "status": result.status,
                "progress": 100,
                "completed_at": utc_now(),
                "summary": SUMMARY_TEMPLATES[result.status],
                "findings": bounded_findings(result.kind, result.findings),
                "error_code": safe_code,
                "error_message": safe_message,
                "screenshot_path": _validated_artifact_path(
                    result.screenshot_path, self._data_root, diagnostic_id
                ),
                "report_path": _validated_artifact_path(
                    result.report_path, self._data_root, diagnostic_id
                ),
            }
            return self._cas_update(session, diagnostic_id, run.status, values)

    def recover_orphans(self) -> int:
        with self._session_factory() as session:
            result = session.execute(
                sql_update(DiagnosticRun)
                .where(DiagnosticRun.status.in_(ACTIVE_STATUSES))
                .values(
                    status="failed",
                    progress=100,
                    completed_at=utc_now(),
                    summary=SUMMARY_TEMPLATES["failed"],
                    error_code="manager_restarted",
                    error_message=ERROR_MESSAGES["manager_restarted"],
                )
                .execution_options(synchronize_session=False)
            )
            session.commit()
            return int(result.rowcount or 0)
