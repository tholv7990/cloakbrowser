from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from math import ceil
from pathlib import Path
import sqlite3
import threading
from uuid import UUID

from sqlalchemy import func, select, update as sql_update
from sqlalchemy.exc import IntegrityError, OperationalError

from ...errors import ManagerError
from ...events import EventBroker, diagnostic_event
from ...models import DiagnosticRun, Profile, utc_now
from .runner import DiagnosticRequest, DiagnosticResult, DiagnosticRunner
from .schemas import DiagnosticResultUpdate, TARGET_URLS, bounded_findings


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
    "cleanup_failed": "The diagnostic could not safely release its browser resources.",
    "profile_not_stopped": "Stop the profile before running this diagnostic.",
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
        "cleanup_failed",
        "profile_not_stopped",
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

    def current(self, diagnostic_id: str) -> DiagnosticRun:
        return self._current(diagnostic_id)

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
            bounded = max(run.progress, max(0, min(100, int(progress))))
            if bounded == run.progress:
                return run
            return self._cas_update(
                session,
                diagnostic_id,
                run.status,
                {"progress": bounded},
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

    def amend_cleanup_failure(
        self, diagnostic_id: str, result: DiagnosticResult
    ) -> DiagnosticRun:
        """Amend only the explicitly correlated run after deferred cleanup fails."""

        if result.status != "failed" or result.error_code != "cleanup_failed":
            return self._current(diagnostic_id)
        with self._session_factory() as session:
            run = get_diagnostic(session, diagnostic_id)
            if run.kind != result.kind:
                raise ManagerError(
                    "diagnostic_result_kind_mismatch",
                    "The result does not match the diagnostic kind.",
                    409,
                )
            values = {
                "status": "failed",
                "progress": 100,
                "completed_at": utc_now(),
                "summary": SUMMARY_TEMPLATES["failed"],
                "findings": {},
                "error_code": "cleanup_failed",
                "error_message": ERROR_MESSAGES["cleanup_failed"],
                "screenshot_path": _validated_artifact_path(
                    result.screenshot_path, self._data_root, diagnostic_id
                ),
                "report_path": _validated_artifact_path(
                    result.report_path, self._data_root, diagnostic_id
                ),
            }
            update_result = session.execute(
                sql_update(DiagnosticRun)
                .where(
                    DiagnosticRun.id == diagnostic_id,
                    DiagnosticRun.status.in_(ACTIVE_STATUSES | TERMINAL_STATUSES),
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            if update_result.rowcount != 1:
                session.rollback()
                raise ManagerError(
                    "diagnostic_not_active",
                    "The diagnostic is no longer active.",
                    409,
                )
            session.commit()
            session.expire_all()
            amended = session.get(DiagnosticRun, diagnostic_id)
            if amended is None:
                raise _not_found()
            return amended


class DiagnosticExecutor:
    """Own asynchronous diagnostic tasks, cancellation signals, and events."""

    def __init__(
        self,
        manager: DiagnosticManager,
        runner: DiagnosticRunner,
        events: EventBroker,
        *,
        cleanup_wait_seconds: float = 0.25,
        shutdown_cleanup_wait_seconds: float = 2.0,
    ) -> None:
        self._manager = manager
        self._runner = runner
        self._events = events
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._deferred_tasks: set[asyncio.Task[None]] = set()
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._cancel_events: dict[str, threading.Event] = {}
        self._cleanup_wait_seconds = cleanup_wait_seconds
        self._shutdown_cleanup_wait_seconds = shutdown_cleanup_wait_seconds
        self._accepting = False
        self._state_lock = threading.Lock()
        self._runner.set_deferred_result_callback(self._deferred_result)

    @property
    def task_count(self) -> int:
        return (
            len(self._tasks)
            + len(self._deferred_tasks)
            + len(self._cleanup_tasks)
            + self._runner.cleanup_ownership_count
        )

    def start(self) -> None:
        loop = asyncio.get_running_loop()
        with self._state_lock:
            self._loop = loop
            self._accepting = True
        self._manager.set_scheduler(self.schedule)

    def schedule(self, diagnostic_id: str) -> None:
        with self._state_lock:
            loop = self._loop
            accepting = self._accepting
        if not accepting or loop is None or loop.is_closed():
            raise RuntimeError("diagnostic scheduler is unavailable")
        loop.call_soon_threadsafe(self._spawn, diagnostic_id)

    def _spawn(self, diagnostic_id: str) -> None:
        if not self._accepting or diagnostic_id in self._tasks:
            if not self._accepting:
                self._manager._mark_scheduler_unavailable(diagnostic_id)
            return
        cancel_event = threading.Event()
        self._cancel_events[diagnostic_id] = cancel_event
        task = asyncio.create_task(
            self._run(diagnostic_id, cancel_event),
            name=f"diagnostic-{diagnostic_id}",
        )
        self._tasks[diagnostic_id] = task

    def _serialize(self, run: DiagnosticRun) -> dict:
        return diagnostic_to_dict(run, self._manager._data_root)

    def _publish(self, event_type: str, run: DiagnosticRun) -> None:
        self._events.publish(
            diagnostic_event(event_type, self._serialize(run))  # type: ignore[arg-type]
        )

    async def _progress(self, diagnostic_id: str, value: int) -> None:
        try:
            before = await asyncio.to_thread(self._manager.current, diagnostic_id)
            run = await asyncio.to_thread(
                self._manager.update_progress, diagnostic_id, value
            )
        except ManagerError:
            return
        if run.progress > before.progress:
            self._publish("diagnostic.progress", run)

    def _progress_from_worker(self, diagnostic_id: str, value: int) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        future = asyncio.run_coroutine_threadsafe(
            self._progress(diagnostic_id, value), loop
        )
        with suppress(Exception):
            future.result(timeout=5)

    def _terminal_from_result(
        self, diagnostic_id: str, result: DiagnosticResult
    ) -> DiagnosticRun:
        if result.status == "cancelled":
            return self._manager.transition(diagnostic_id, "cancelled")
        update = DiagnosticResultUpdate(
            kind=result.kind,
            status=result.status,
            findings=result.findings,
            error_code=result.error_code,
            screenshot_path=result.screenshot_path,
            report_path=result.report_path,
        )
        return self._manager.store_result(diagnostic_id, update)

    async def _retry_active_write(
        self, diagnostic_id: str, operation: Callable[[], DiagnosticRun]
    ) -> DiagnosticRun:
        while True:
            try:
                return await asyncio.to_thread(operation)
            except ManagerError as error:
                if error.code != "diagnostic_conflict":
                    raise
                current = await asyncio.to_thread(
                    self._manager.current, diagnostic_id
                )
                if current.status in TERMINAL_STATUSES:
                    return current
                await asyncio.sleep(0.02)

    async def _observe_cleanup(self, run_id: UUID) -> None:
        released = await asyncio.to_thread(
            self._runner.wait_for_cleanup, run_id, None
        )
        if released:
            self._runner.acknowledge_cleanup(run_id)

    def _spawn_cleanup_observer(self, run_id: UUID) -> None:
        task = asyncio.create_task(
            self._observe_cleanup(run_id),
            name=f"diagnostic-cleanup-owner-{run_id}",
        )
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    async def _run(
        self, diagnostic_id: str, cancel_event: threading.Event
    ) -> None:
        terminal_owned = False
        try:
            run = await self._retry_active_write(
                diagnostic_id,
                lambda: self._manager.transition(diagnostic_id, "running"),
            )
            if run.status in TERMINAL_STATUSES:
                terminal_owned = True
                self._publish("diagnostic.completed", run)
                return
            self._publish("diagnostic.progress", run)
            request = DiagnosticRequest(
                run_id=run.id,
                kind=run.kind,
                target_url=TARGET_URLS[run.kind],
                profile_id=run.profile_id,
            )
            run_uuid = UUID(run.id)
            self._runner.begin_cleanup_ownership(run_uuid)
            result = await asyncio.to_thread(
                self._runner.run,
                request,
                cancel_event,
                lambda value: self._progress_from_worker(
                    diagnostic_id, value
                ),
            )
            cleanup_released = await asyncio.to_thread(
                self._runner.wait_for_cleanup,
                run_uuid,
                self._cleanup_wait_seconds,
            )
            if cleanup_released:
                self._runner.acknowledge_cleanup(run_uuid)
            else:
                result = DiagnosticResult(
                    kind=result.kind,
                    status="failed",
                    findings={},
                    error_code="cleanup_failed",
                    report_path=result.report_path,
                )
                self._spawn_cleanup_observer(run_uuid)
            try:
                terminal = await self._retry_active_write(
                    diagnostic_id,
                    lambda: self._terminal_from_result(diagnostic_id, result),
                )
            except ManagerError as error:
                if error.code not in {"diagnostic_not_active", "diagnostic_conflict"}:
                    raise
                terminal = await asyncio.to_thread(
                    self._manager.current, diagnostic_id
                )
            if terminal.status in TERMINAL_STATUSES:
                terminal_owned = True
                self._publish("diagnostic.completed", terminal)
        except ManagerError as error:
            with suppress(ManagerError):
                current = await asyncio.to_thread(
                    self._manager.current, diagnostic_id
                )
                if current.status in TERMINAL_STATUSES:
                    terminal = current
                elif error.code not in {
                    "diagnostic_not_active",
                    "diagnostic_conflict",
                }:
                    terminal = await self._retry_active_write(
                        diagnostic_id,
                        lambda: self._manager.transition(
                            diagnostic_id, "failed"
                        ),
                    )
                else:
                    terminal = current
                terminal_owned = terminal.status in TERMINAL_STATUSES
                if terminal_owned:
                    self._publish("diagnostic.completed", terminal)
        except Exception:
            with suppress(ManagerError):
                current = await asyncio.to_thread(
                    self._manager.current, diagnostic_id
                )
                terminal = await self._retry_active_write(
                    diagnostic_id,
                    lambda: self._manager.transition(
                        diagnostic_id, "failed"
                    ),
                ) if current.status in ACTIVE_STATUSES else current
                terminal_owned = terminal.status in TERMINAL_STATUSES
                self._publish("diagnostic.completed", terminal)
        finally:
            if terminal_owned:
                self._cancel_events.pop(diagnostic_id, None)
                self._tasks.pop(diagnostic_id, None)

    async def cancel(self, diagnostic_id: str) -> DiagnosticRun:
        current = await asyncio.to_thread(self._manager.current, diagnostic_id)
        if current.status not in ACTIVE_STATUSES:
            raise ManagerError(
                "diagnostic_not_active", "The diagnostic is no longer active.", 409
            )
        await asyncio.sleep(0)
        cancel_event = self._cancel_events.get(diagnostic_id)
        task = self._tasks.get(diagnostic_id)
        if cancel_event is None or task is None:
            terminal = await asyncio.to_thread(
                self._manager.transition, diagnostic_id, "cancelled"
            )
            self._publish("diagnostic.completed", terminal)
            return terminal
        cancel_event.set()
        await asyncio.shield(task)
        return await asyncio.to_thread(self._manager.current, diagnostic_id)

    def _deferred_result(self, run_id: UUID, result: DiagnosticResult) -> None:
        with self._state_lock:
            loop = self._loop
            accepting = self._accepting
        if not accepting or loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._spawn_deferred, run_id, result)

    def _spawn_deferred(self, run_id: UUID, result: DiagnosticResult) -> None:
        if not self._accepting:
            return
        task = asyncio.create_task(
            self._apply_deferred_result(str(run_id), result),
            name=f"diagnostic-deferred-{run_id}",
        )
        self._deferred_tasks.add(task)
        task.add_done_callback(self._deferred_tasks.discard)

    async def _apply_deferred_result(
        self, diagnostic_id: str, result: DiagnosticResult
    ) -> None:
        try:
            amended = await asyncio.to_thread(
                self._manager.amend_cleanup_failure, diagnostic_id, result
            )
        except ManagerError:
            return
        self._publish("diagnostic.completed", amended)

    async def shutdown(self) -> None:
        with self._state_lock:
            self._accepting = False
        for cancel_event in tuple(self._cancel_events.values()):
            cancel_event.set()
        tasks = tuple(self._tasks.values())
        if tasks:
            _done, pending = await asyncio.wait(
                tasks, timeout=self._shutdown_cleanup_wait_seconds
            )
            if pending:
                raise RuntimeError(
                    "diagnostic workers still own active persistence or cleanup"
                )
        deferred_tasks = tuple(self._deferred_tasks)
        if deferred_tasks:
            _done, pending = await asyncio.wait(
                deferred_tasks,
                timeout=self._shutdown_cleanup_wait_seconds,
            )
            if pending:
                raise RuntimeError("deferred diagnostic results remain owned")
        cleanup_tasks = tuple(self._cleanup_tasks)
        if cleanup_tasks:
            _done, pending = await asyncio.wait(
                cleanup_tasks,
                timeout=self._shutdown_cleanup_wait_seconds,
            )
            if pending:
                raise RuntimeError("diagnostic cleanup remains owned")
        if self._runner.cleanup_ownership_count:
            raise RuntimeError("diagnostic cleanup could not be safely released")
        for diagnostic_id in tuple(self._tasks):
            current = await asyncio.to_thread(
                self._manager.current, diagnostic_id
            )
            if current.status in ACTIVE_STATUSES:
                raise RuntimeError(
                    "diagnostic persistence remains active during shutdown"
                )
        self._tasks.clear()
        self._cancel_events.clear()
        self._deferred_tasks.clear()
        self._cleanup_tasks.clear()
