from __future__ import annotations

import hashlib
import re
import secrets
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from ...config import ManagerSettings
from ...models import Profile
from ..runtime.launcher import (
    enabled_profile_extension_paths,
    profile_launch_snapshot,
)
from ..runtime.locks import ProfileFileLock
from ..runtime.service import active_runtime
from .artifacts import (
    ArtifactBoundaryError,
    diagnostic_run_root,
    write_diagnostic_artifacts,
)
from .schemas import (
    DiagnosticErrorCode,
    DiagnosticKind,
    TARGET_URLS,
    bounded_findings,
)


_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,4}$")
_TIERS = frozenset({"free", "solo", "team", "business", "pro", "override"})
_PROXY_CLASSIFICATIONS = frozenset(
    {"direct", "residential", "datacenter", "mobile", "unknown"}
)
_WARNING_CODES = frozenset(
    {"target_layout_changed", "captcha_user_action_required"}
)
_FAILURE_CODES = frozenset(
    {
        "diagnostic_failed",
        "browser_crashed",
        "cleanup_failed",
        "proxy_preflight_failed",
        "network_error",
        "timeout",
        "target_layout_changed",
    }
)
_TARGET_ROUTES = {
    "direct_google_control": frozenset(
        {
            ("www.google.com", "/search"),
            ("www.google.com", "/sorry/index"),
            ("consent.google.com", "/m"),
        }
    ),
    "google_search": frozenset(
        {
            ("www.google.com", "/search"),
            ("www.google.com", "/sorry/index"),
            ("consent.google.com", "/m"),
        }
    ),
    "pixelscan": frozenset({("pixelscan.net", "/")}),
    "iphey": frozenset({("iphey.com", "/")}),
    "cloudflare": frozenset(
        {("challenge.cloudflare.com", "/turnstile/v0/generic/")}
    ),
}
_LIMITATIONS = (
    "This is a timestamped observation, not a permanent fingerprint guarantee.",
    "No raw DOM, storage, cookies, response bodies, or network bodies are retained.",
)
_CLEANUP_GRACE_SECONDS = 0.025


class DiagnosticBrowserCrashed(Exception):
    pass


class DiagnosticNetworkError(Exception):
    pass


class BrowserSession(Protocol):
    def close(self) -> None: ...

    def terminate(self) -> None: ...

    def is_closed(self) -> bool: ...


class BrowserAdapter(Protocol):
    def launch(
        self,
        snapshot: dict[str, Any],
        *,
        timeout_seconds: float,
        cancel_event: threading.Event,
    ) -> "BrowserLaunch": ...


class TargetAdapter(Protocol):
    def run(
        self,
        session: BrowserSession,
        target_url: str,
        *,
        timeout_seconds: float,
        cancel_event: threading.Event,
        progress: Callable[[int], None],
    ) -> "TargetResult": ...


@dataclass(frozen=True, slots=True)
class DiagnosticRequest:
    run_id: str
    kind: DiagnosticKind | str
    target_url: str
    profile_id: str | None = None


@dataclass(frozen=True, slots=True)
class BrowserLaunch:
    session: BrowserSession
    tier: str
    version: str


@dataclass(frozen=True, slots=True)
class ProxyPreflightResult:
    proxy_url: str | None = None
    checked_at: datetime | None = None
    classification: str | None = None


@dataclass(frozen=True, slots=True)
class TargetResult:
    status: Literal["passed", "warning", "failed"]
    findings: dict[str, bool | str]
    final_url: str
    title: str
    screenshot: bytes | None
    error_code: DiagnosticErrorCode | None = None


@dataclass(frozen=True, slots=True)
class _LifecycleResult:
    launch: BrowserLaunch | None
    target: TargetResult | None
    error: Exception | None
    cleanup_safe: bool
    cleanup_had_error: bool


@dataclass(frozen=True, slots=True)
class DiagnosticResult:
    kind: str
    status: Literal["passed", "warning", "failed", "cancelled"]
    findings: dict[str, bool | str]
    error_code: str | None = None
    screenshot_path: str | None = None
    report_path: str | None = None


DeferredDiagnosticResultCallback = Callable[[UUID, DiagnosticResult], None]


class _RunnerFailure(Exception):
    def __init__(self, code: str):
        self.code = code


class _Cancelled(Exception):
    pass


@dataclass(slots=True)
class _Operation:
    name: str
    done: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    abandoned: bool = False
    result: Any = None
    error: Exception | None = None
    completed_at: float | None = None
    late_cleanup_safe: bool = True
    late_cleanup_had_error: bool = False
    late_cleanup: Callable[[Any], tuple[bool, bool]] | None = None
    abandon_callback: Callable[[], tuple[bool, bool]] | None = None
    interrupt_done: threading.Event = field(default_factory=threading.Event)
    interrupt_safe: bool = False
    interrupt_had_error: bool = False


class _OperationTimedOut(TimeoutError):
    def __init__(self, operation: _Operation):
        self.operation = operation


class _OperationCancelled(_Cancelled):
    def __init__(self, operation: _Operation):
        self.operation = operation


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_browser_identity(launch: BrowserLaunch) -> dict[str, str]:
    tier = (
        launch.tier
        if isinstance(launch.tier, str) and launch.tier in _TIERS
        else "unknown"
    )
    version = (
        launch.version
        if isinstance(launch.version, str) and _VERSION.fullmatch(launch.version)
        else "unknown"
    )
    return {"tier": tier, "version": version}


def _safe_title(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:200]


def _sanitized_target_url(kind: str, value: object, request_url: str) -> str:
    fallback = urlsplit(request_url)
    safe_fallback = urlunsplit(
        ("https", fallback.hostname or "", fallback.path or "/", "", "")
    )
    if not isinstance(value, str) or len(value) > 2048:
        return safe_fallback
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").casefold()
        port = parsed.port
    except (ValueError, AttributeError):
        return safe_fallback
    path = parsed.path or "/"
    if (
        parsed.scheme.casefold() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or (host, path) not in _TARGET_ROUTES.get(kind, frozenset())
    ):
        return safe_fallback
    return urlunsplit(("https", host, path, "", ""))


def _normalized_target_error(status: str, value: object) -> str | None:
    code = value if isinstance(value, str) else None
    if status == "passed":
        return None
    if status == "warning":
        if code is None:
            return None
        return code if code in _WARNING_CODES else "target_layout_changed"
    if status == "failed":
        return code if code in _FAILURE_CODES else "diagnostic_failed"
    return "diagnostic_failed"


class DiagnosticRunner:
    """Safe synchronous runner boundary for manager-owned worker threads."""

    def __init__(
        self,
        session_factory,
        settings: ManagerSettings,
        *,
        browser_adapter: BrowserAdapter,
        target_adapter: TargetAdapter,
        proxy_preflight: Callable[[dict[str, Any]], ProxyPreflightResult],
        lock_factory: Callable[[str], Any] | None = None,
        deferred_result: DeferredDiagnosticResultCallback | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._browser_adapter = browser_adapter
        self._target_adapter = target_adapter
        self._proxy_preflight = proxy_preflight
        self._lock_factory = lock_factory or (
            lambda profile_id: ProfileFileLock(
                settings.profile_root / profile_id / ".runtime.lock", profile_id
            )
        )
        self._deferred_result = deferred_result
        self._semaphore = threading.BoundedSemaphore(
            settings.max_concurrent_diagnostics
        )

    @staticmethod
    def _emit(progress: Callable[[int], None], value: int) -> None:
        try:
            progress(max(0, min(100, int(value))))
        except Exception:
            pass

    @staticmethod
    def _check_cancel(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise _Cancelled

    def _remaining(self, deadline: float, cancel_event: threading.Event) -> float:
        self._check_cancel(cancel_event)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        return remaining

    @staticmethod
    def _cleanup_launch(launch: BrowserLaunch) -> tuple[bool, bool]:
        """Return (verified_closed, cleanup_had_error)."""

        had_error = False
        try:
            launch.session.close()
        except Exception:
            had_error = True
        try:
            closed = bool(launch.session.is_closed())
        except Exception:
            had_error = True
            closed = False
        if not closed:
            try:
                launch.session.terminate()
            except Exception:
                had_error = True
            try:
                closed = bool(launch.session.is_closed())
            except Exception:
                had_error = True
                closed = False
        if not closed:
            had_error = True
        return closed, had_error

    @staticmethod
    def _force_terminate(holder: dict[str, Any], holder_lock: threading.Lock):
        with holder_lock:
            launch = holder.get("launch")
        if not isinstance(launch, BrowserLaunch):
            return True, False
        try:
            if launch.session.is_closed():
                return True, False
        except Exception:
            pass
        had_error = False
        try:
            launch.session.terminate()
        except Exception:
            had_error = True
        try:
            safe = bool(launch.session.is_closed())
        except Exception:
            safe = False
            had_error = True
        return safe, had_error or not safe

    def _execute_lifecycle(
        self,
        *,
        snapshot: dict[str, Any],
        request: DiagnosticRequest,
        deadline: float,
        abort_event: threading.Event,
        holder: dict[str, Any],
        holder_lock: threading.Lock,
        progress: Callable[[int], None],
    ) -> _LifecycleResult:
        launch = None
        target = None
        error = None
        cleanup_safe = True
        cleanup_had_error = False
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or abort_event.is_set():
                raise TimeoutError
            launch = self._browser_adapter.launch(
                snapshot,
                timeout_seconds=remaining,
                cancel_event=abort_event,
            )
            if not isinstance(launch, BrowserLaunch):
                raise DiagnosticBrowserCrashed
            with holder_lock:
                holder["launch"] = launch
            if abort_event.is_set():
                raise _Cancelled
            self._emit(progress, 45)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            target = self._target_adapter.run(
                launch.session,
                request.target_url,
                timeout_seconds=remaining,
                cancel_event=abort_event,
                progress=lambda value: self._emit(
                    progress, max(45, min(85, value))
                ),
            )
            if abort_event.is_set():
                raise _Cancelled
        except Exception as caught:
            error = caught
        finally:
            if launch is not None:
                cleanup_safe, cleanup_had_error = self._cleanup_launch(launch)
        return _LifecycleResult(
            launch=launch,
            target=target,
            error=error,
            cleanup_safe=cleanup_safe,
            cleanup_had_error=cleanup_had_error,
        )

    @staticmethod
    def _late_lifecycle_state(value: Any) -> tuple[bool, bool]:
        if not isinstance(value, _LifecycleResult):
            return False, True
        return value.cleanup_safe, value.cleanup_had_error

    def _abandon_operation(self, operation: _Operation) -> None:
        late_result = None
        has_late_result = False
        should_interrupt = False
        with operation.lock:
            if operation.abandoned:
                return
            operation.abandoned = True
            should_interrupt = (
                operation.abandon_callback is not None
                and operation.completed_at is None
            )
            if operation.completed_at is not None and operation.error is None:
                late_result = operation.result
                has_late_result = True
        if has_late_result and operation.late_cleanup is not None:
            try:
                (
                    operation.late_cleanup_safe,
                    operation.late_cleanup_had_error,
                ) = operation.late_cleanup(late_result)
            except Exception:
                operation.late_cleanup_safe = False
                operation.late_cleanup_had_error = True
        if not should_interrupt or operation.abandon_callback is None:
            operation.interrupt_safe = True
            operation.interrupt_done.set()
            return

        def interrupt() -> None:
            try:
                safe, had_error = operation.abandon_callback()
            except Exception:
                safe, had_error = False, True
            with operation.lock:
                operation.interrupt_safe = safe
                operation.interrupt_had_error = had_error
            operation.interrupt_done.set()

        threading.Thread(
            target=interrupt,
            name=f"diagnostic-interrupt-{operation.name}",
            daemon=True,
        ).start()

    def _bounded_call(
        self,
        name: str,
        function: Callable[[], Any],
        *,
        deadline: float,
        cancel_event: threading.Event,
        late_cleanup: Callable[[Any], tuple[bool, bool]] | None = None,
        abandon_callback: Callable[[], tuple[bool, bool]] | None = None,
    ) -> Any:
        operation = _Operation(
            name=name,
            late_cleanup=late_cleanup,
            abandon_callback=abandon_callback,
        )
        if abandon_callback is None:
            operation.interrupt_safe = True
            operation.interrupt_done.set()

        def invoke() -> None:
            value = None
            error = None
            try:
                value = function()
            except Exception as caught:
                error = caught
            completed_at = time.monotonic()
            cleanup_value = None
            should_cleanup = False
            with operation.lock:
                operation.completed_at = completed_at
                operation.error = error
                operation.result = value
                if operation.abandoned:
                    cleanup_value = value
                    should_cleanup = error is None
            if should_cleanup and operation.late_cleanup is not None:
                try:
                    (
                        operation.late_cleanup_safe,
                        operation.late_cleanup_had_error,
                    ) = operation.late_cleanup(cleanup_value)
                except Exception:
                    operation.late_cleanup_safe = False
                    operation.late_cleanup_had_error = True
            operation.done.set()

        threading.Thread(
            target=invoke,
            name=f"diagnostic-adapter-{name}",
            daemon=True,
        ).start()

        while True:
            if cancel_event.is_set():
                self._abandon_operation(operation)
                raise _OperationCancelled(operation)
            now = time.monotonic()
            if now >= deadline:
                self._abandon_operation(operation)
                raise _OperationTimedOut(operation)
            if not operation.done.wait(timeout=min(0.005, deadline - now)):
                continue
            if cancel_event.is_set():
                self._abandon_operation(operation)
                raise _OperationCancelled(operation)
            with operation.lock:
                completed_at = operation.completed_at
                error = operation.error
                value = operation.result
            if completed_at is None or completed_at > deadline:
                self._abandon_operation(operation)
                raise _OperationTimedOut(operation)
            if error is not None:
                raise error
            return value

    def _defer_operation_resources(
        self,
        operation: _Operation,
        *,
        request: DiagnosticRequest,
        snapshot: dict[str, Any] | None,
        preflight: ProxyPreflightResult | None,
        started: float,
        temporary_profile: Path | None,
        profile_lock: Any,
        release_slot: bool,
    ) -> None:
        """Keep ownership until an abandoned operation is verified safe."""

        def reap() -> None:
            operation.done.wait()
            operation.interrupt_done.wait()
            safe = operation.late_cleanup_safe
            cleanup_failed = (
                operation.late_cleanup_had_error
                or operation.interrupt_had_error
                or not safe
            )
            if safe and temporary_profile is not None:
                try:
                    shutil.rmtree(temporary_profile)
                except OSError:
                    safe = False
                    cleanup_failed = True
            if safe and profile_lock is not None:
                try:
                    profile_lock.release()
                except Exception:
                    safe = False
                    cleanup_failed = True
            if safe and release_slot:
                self._semaphore.release()

            if not cleanup_failed:
                return
            launch = None
            target = None
            with operation.lock:
                value = operation.result
            if isinstance(value, _LifecycleResult):
                launch = value.launch
                target = value.target
            report_path = None
            try:
                report = self._report(
                    request=request,
                    launch=launch,
                    snapshot=snapshot,
                    preflight=preflight,
                    started=started,
                    target=target,
                    status="failed",
                    error_code="cleanup_failed",
                )
                report_path = self._artifacts(request, report, None).report_path
            except (ArtifactBoundaryError, OSError, ValueError, TypeError):
                pass
            result = DiagnosticResult(
                kind=str(request.kind),
                status="failed",
                findings={},
                error_code="cleanup_failed",
                report_path=report_path,
            )
            if self._deferred_result is not None:
                try:
                    self._deferred_result(UUID(request.run_id), result)
                except Exception:
                    pass

        threading.Thread(
            target=reap,
            name=f"diagnostic-cleanup-{operation.name}",
            daemon=True,
        ).start()

    def _acquire_slot(
        self, deadline: float, cancel_event: threading.Event
    ) -> None:
        while True:
            remaining = self._remaining(deadline, cancel_event)
            if self._semaphore.acquire(timeout=min(0.05, remaining)):
                return

    @staticmethod
    def _validate_request(request: DiagnosticRequest) -> None:
        expected = TARGET_URLS.get(request.kind)
        try:
            parsed = urlsplit(request.target_url)
        except ValueError:
            raise _RunnerFailure("diagnostic_failed") from None
        if (
            expected is None
            or request.target_url != expected
            or parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise _RunnerFailure("diagnostic_failed")
        if request.kind == "direct_google_control":
            if request.profile_id is not None:
                raise _RunnerFailure("diagnostic_failed")
        elif not request.profile_id:
            raise _RunnerFailure("diagnostic_failed")

    def _profile_snapshot(self, profile_id: str) -> tuple[dict[str, Any], Any]:
        profile_lock = self._lock_factory(profile_id)
        profile_lock.acquire()
        try:
            with self._session_factory() as session:
                profile = session.get(Profile, profile_id)
                if profile is None or profile.deleted_at is not None:
                    raise _RunnerFailure("diagnostic_failed")
                if active_runtime(session, profile_id) is not None:
                    raise _RunnerFailure("profile_not_stopped")
                extension_paths = enabled_profile_extension_paths(
                    session, profile_id, self._settings
                )
                return (
                    profile_launch_snapshot(
                        profile,
                        self._settings,
                        extension_paths=extension_paths,
                    ),
                    profile_lock,
                )
        except Exception:
            profile_lock.release()
            raise

    def _direct_snapshot(self, run_root: Path) -> tuple[dict[str, Any], Path]:
        profile_dir = Path(tempfile.mkdtemp(prefix="profile-", dir=run_root))
        try:
            seed = str(secrets.randbelow(9_000_000_000) + 1_000_000_000)
            fingerprint_hash = hashlib.sha256(seed.encode("ascii")).hexdigest()
            profile = SimpleNamespace(
                id=f"diagnostic-{run_root.name}",
                fingerprint_seed=seed,
                fingerprint_preset="consistent",
                fingerprint_revision=1,
                fingerprint_config_hash=fingerprint_hash,
                browser_version_mode="installed",
                browser_version=None,
                user_agent_mode="automatic",
                custom_user_agent=None,
                location={
                    "geo_mode": "system",
                    "locale": None,
                    "timezone": None,
                    "webrtc_mode": "direct",
                    "geolocation_mode": "ask",
                },
                window={"mode": "maximized", "color_scheme": "system"},
                behavior={
                    "humanize_enabled": False,
                    "humanize_preset": "default",
                    "restore_previous_tabs": False,
                    "ignore_https_errors": False,
                },
                startup_urls=[],
                proxy_id=None,
            )
            snapshot = profile_launch_snapshot(
                profile, self._settings, extension_paths=[]
            )
            snapshot["profile_dir"] = profile_dir
            return snapshot, profile_dir
        except Exception:
            shutil.rmtree(profile_dir, ignore_errors=True)
            raise

    def _report(
        self,
        *,
        request: DiagnosticRequest,
        launch: BrowserLaunch | None,
        snapshot: dict[str, Any] | None,
        preflight: ProxyPreflightResult | None,
        started: float,
        target: TargetResult | None,
        status: str,
        error_code: str | None,
    ) -> dict[str, Any]:
        findings = bounded_findings(
            str(request.kind), target.findings if target is not None else {}
        )
        profile = None
        if snapshot is not None:
            profile = {
                "fingerprint_revision": int(
                    snapshot.get("fingerprint_revision") or 0
                ),
                "fingerprint_config_hash": (
                    snapshot.get("fingerprint_config_hash")
                    if isinstance(snapshot.get("fingerprint_config_hash"), str)
                    and re.fullmatch(
                        r"[0-9a-f]{64}", snapshot["fingerprint_config_hash"]
                    )
                    else None
                ),
            }
        proxy = None
        if preflight is not None:
            classification = (
                preflight.classification
                if preflight.classification in _PROXY_CLASSIFICATIONS
                else "unknown"
            )
            proxy = {
                "checked_at": _utc_iso(preflight.checked_at),
                "classification": classification,
            }
        safe_kind = (
            str(request.kind)
            if request.kind in TARGET_URLS
            else "direct_google_control"
        )
        requested_url = TARGET_URLS[safe_kind]
        target_report = {
            "requested_url": requested_url,
            "final_url": _sanitized_target_url(
                safe_kind,
                target.final_url if target is not None else requested_url,
                requested_url,
            ),
            "title": _safe_title(target.title if target is not None else ""),
        }
        return {
            "browser": (
                _safe_browser_identity(launch)
                if launch is not None
                else {"tier": "unknown", "version": "unknown"}
            ),
            "error_code": error_code,
            "findings": findings,
            "kind": safe_kind,
            "limitations": list(_LIMITATIONS),
            "observed_at": _utc_iso(datetime.now(timezone.utc)),
            "profile": profile,
            "proxy": proxy,
            "status": status,
            "target": target_report,
            "timings": {"duration_ms": max(0, round((time.monotonic() - started) * 1000))},
        }

    def _artifacts(
        self,
        request: DiagnosticRequest,
        report: dict[str, Any],
        screenshot: bytes | None,
    ):
        return write_diagnostic_artifacts(
            self._settings.data_root,
            request.run_id,
            report=report,
            screenshot=screenshot,
            max_report_bytes=self._settings.diagnostic_max_report_bytes,
            max_screenshot_bytes=self._settings.diagnostic_max_screenshot_bytes,
        )

    @staticmethod
    def _failure_code(error: BaseException) -> str:
        if isinstance(error, _RunnerFailure):
            return error.code
        if isinstance(error, TimeoutError):
            return "timeout"
        if isinstance(error, DiagnosticBrowserCrashed):
            return "browser_crashed"
        if isinstance(error, DiagnosticNetworkError):
            return "network_error"
        return "diagnostic_failed"

    def run(
        self,
        request: DiagnosticRequest,
        cancel_event: threading.Event,
        progress: Callable[[int], None],
    ) -> DiagnosticResult:
        started = time.monotonic()
        deadline = started + self._settings.diagnostic_timeout_seconds
        slot_acquired = False
        profile_lock = None
        temporary_profile = None
        launch = None
        snapshot = None
        preflight = None
        target = None
        pending_operation: _Operation | None = None
        lifecycle_result: _LifecycleResult | None = None
        outcome: DiagnosticResult | None = None
        try:
            self._validate_request(request)
            self._acquire_slot(deadline, cancel_event)
            slot_acquired = True
            self._emit(progress, 5)
            self._check_cancel(cancel_event)

            if request.kind == "direct_google_control":
                run_root = diagnostic_run_root(
                    self._settings.data_root, request.run_id
                )
                snapshot, temporary_profile = self._direct_snapshot(run_root)
                preflight = ProxyPreflightResult(
                    proxy_url=None, checked_at=None, classification="direct"
                )
            else:
                snapshot, profile_lock = self._profile_snapshot(request.profile_id or "")
                snapshot["startup_urls"] = []
                self._check_cancel(cancel_event)
                try:
                    preflight = self._bounded_call(
                        "preflight",
                        lambda: self._proxy_preflight(snapshot),
                        deadline=deadline,
                        cancel_event=cancel_event,
                    )
                except (_OperationTimedOut, _OperationCancelled) as abandoned:
                    pending_operation = abandoned.operation
                    raise
                except Exception:
                    raise _RunnerFailure("proxy_preflight_failed") from None
                if not isinstance(preflight, ProxyPreflightResult):
                    raise _RunnerFailure("proxy_preflight_failed")
            snapshot["proxy_url"] = preflight.proxy_url
            self._emit(progress, 25)

            lifecycle_abort = threading.Event()
            lifecycle_holder: dict[str, Any] = {}
            lifecycle_holder_lock = threading.Lock()
            try:
                lifecycle_result = self._bounded_call(
                    "lifecycle",
                    lambda: self._execute_lifecycle(
                        snapshot=snapshot,
                        request=request,
                        deadline=deadline,
                        abort_event=lifecycle_abort,
                        holder=lifecycle_holder,
                        holder_lock=lifecycle_holder_lock,
                        progress=progress,
                    ),
                    deadline=deadline,
                    cancel_event=cancel_event,
                    late_cleanup=self._late_lifecycle_state,
                    abandon_callback=lambda: (
                        lifecycle_abort.set()
                        or self._force_terminate(
                            lifecycle_holder, lifecycle_holder_lock
                        )
                    ),
                )
            except (_OperationTimedOut, _OperationCancelled) as abandoned:
                pending_operation = abandoned.operation
                raise
            if not isinstance(lifecycle_result, _LifecycleResult):
                raise DiagnosticBrowserCrashed
            launch = lifecycle_result.launch
            target = lifecycle_result.target
            if lifecycle_result.error is not None:
                error = lifecycle_result.error
                if isinstance(error, _Cancelled):
                    raise error
                if isinstance(error, (TimeoutError, DiagnosticBrowserCrashed, DiagnosticNetworkError)):
                    raise error
                if launch is None:
                    raise DiagnosticBrowserCrashed from None
                raise error
            self._check_cancel(cancel_event)
            if not isinstance(target, TargetResult):
                raise _RunnerFailure("diagnostic_failed")
            if target.status not in {"passed", "warning", "failed"}:
                raise _RunnerFailure("diagnostic_failed")
            findings = bounded_findings(str(request.kind), target.findings)
            error_code = _normalized_target_error(
                target.status, target.error_code
            )
            report = self._report(
                request=request,
                launch=launch,
                snapshot=snapshot,
                preflight=preflight,
                started=started,
                target=target,
                status=target.status,
                error_code=error_code,
            )
            artifacts = self._artifacts(request, report, target.screenshot)
            self._emit(progress, 95)
            outcome = DiagnosticResult(
                kind=str(request.kind),
                status=target.status,
                findings=findings,
                error_code=error_code,
                screenshot_path=artifacts.screenshot_path,
                report_path=artifacts.report_path,
            )
        except (_Cancelled, _OperationCancelled):
            outcome = DiagnosticResult(
                kind=str(request.kind), status="cancelled", findings={}
            )
        except Exception as error:
            code = self._failure_code(error)
            report_path = None
            try:
                report = self._report(
                    request=request,
                    launch=launch,
                    snapshot=snapshot,
                    preflight=preflight,
                    started=started,
                    target=target,
                    status="failed",
                    error_code=code,
                )
                report_path = self._artifacts(request, report, None).report_path
            except (ArtifactBoundaryError, OSError, ValueError, TypeError):
                pass
            outcome = DiagnosticResult(
                kind=str(request.kind),
                status="failed",
                findings={},
                error_code=code,
                report_path=report_path,
            )

        if outcome is None:
            outcome = DiagnosticResult(
                kind=str(request.kind),
                status="failed",
                findings={},
                error_code="diagnostic_failed",
            )

        if pending_operation is not None:
            cleanup_deadline = time.monotonic() + _CLEANUP_GRACE_SECONDS
            pending_operation.interrupt_done.wait(_CLEANUP_GRACE_SECONDS)
            remaining = cleanup_deadline - time.monotonic()
            if remaining > 0:
                pending_operation.done.wait(remaining)

        if pending_operation is not None and (
            not pending_operation.done.is_set()
            or not pending_operation.interrupt_done.is_set()
        ):
            self._defer_operation_resources(
                pending_operation,
                request=request,
                snapshot=snapshot,
                preflight=preflight,
                started=started,
                temporary_profile=temporary_profile,
                profile_lock=profile_lock,
                release_slot=slot_acquired,
            )
            if (
                not pending_operation.interrupt_done.is_set()
                or not pending_operation.interrupt_safe
                or pending_operation.interrupt_had_error
            ):
                report_path = None
                try:
                    report = self._report(
                        request=request,
                        launch=launch,
                        snapshot=snapshot,
                        preflight=preflight,
                        started=started,
                        target=target,
                        status="failed",
                        error_code="cleanup_failed",
                    )
                    report_path = self._artifacts(
                        request, report, None
                    ).report_path
                except (
                    ArtifactBoundaryError,
                    OSError,
                    ValueError,
                    TypeError,
                ):
                    pass
                outcome = DiagnosticResult(
                    kind=str(request.kind),
                    status="failed",
                    findings={},
                    error_code="cleanup_failed",
                    report_path=report_path,
                )
            return outcome

        cleanup_failed = False
        browser_safe = True
        if pending_operation is not None:
            browser_safe = pending_operation.late_cleanup_safe
            cleanup_failed = (
                pending_operation.late_cleanup_had_error
                or pending_operation.interrupt_had_error
                or not pending_operation.interrupt_safe
                or not browser_safe
            )
            with pending_operation.lock:
                late_result = pending_operation.result
            if isinstance(late_result, _LifecycleResult):
                lifecycle_result = late_result
                launch = late_result.launch
                target = late_result.target
        elif lifecycle_result is not None:
            browser_safe = lifecycle_result.cleanup_safe
            cleanup_failed = (
                lifecycle_result.cleanup_had_error or not browser_safe
            )
        elif launch is not None:
            browser_safe, close_failed = self._cleanup_launch(launch)
            cleanup_failed = close_failed or not browser_safe

        if temporary_profile is not None and browser_safe:
            try:
                shutil.rmtree(temporary_profile)
            except OSError:
                cleanup_failed = True

        if profile_lock is not None and browser_safe:
            try:
                profile_lock.release()
            except Exception:
                cleanup_failed = True

        if slot_acquired and browser_safe:
            self._semaphore.release()

        if cleanup_failed:
            report_path = None
            try:
                report = self._report(
                    request=request,
                    launch=launch,
                    snapshot=snapshot,
                    preflight=preflight,
                    started=started,
                    target=target,
                    status="failed",
                    error_code="cleanup_failed",
                )
                report_path = self._artifacts(request, report, None).report_path
            except (ArtifactBoundaryError, OSError, ValueError, TypeError):
                pass
            return DiagnosticResult(
                kind=str(request.kind),
                status="failed",
                findings={},
                error_code="cleanup_failed",
                screenshot_path=outcome.screenshot_path,
                report_path=report_path,
            )

        return outcome
