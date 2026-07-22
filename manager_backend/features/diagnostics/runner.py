from __future__ import annotations

import hashlib
import re
import secrets
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

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
        "proxy_preflight_failed",
        "network_error",
        "timeout",
        "target_layout_changed",
    }
)
_LIMITATIONS = (
    "This is a timestamped observation, not a permanent fingerprint guarantee.",
    "No raw DOM, storage, cookies, response bodies, or network bodies are retained.",
)


class DiagnosticBrowserCrashed(Exception):
    pass


class DiagnosticNetworkError(Exception):
    pass


class BrowserSession(Protocol):
    def close(self) -> None: ...


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
class DiagnosticResult:
    kind: str
    status: Literal["passed", "warning", "failed", "cancelled"]
    findings: dict[str, bool | str]
    error_code: str | None = None
    screenshot_path: str | None = None
    report_path: str | None = None


class _RunnerFailure(Exception):
    def __init__(self, code: str):
        self.code = code


class _Cancelled(Exception):
    pass


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


def _safe_final_url(value: object, request_url: str) -> str:
    if not isinstance(value, str) or value not in TARGET_URLS.values():
        return request_url
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return request_url
    return value


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
            "final_url": _safe_final_url(
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
                self._check_cancel(cancel_event)
                try:
                    preflight = self._proxy_preflight(snapshot)
                except Exception:
                    raise _RunnerFailure("proxy_preflight_failed") from None
                if not isinstance(preflight, ProxyPreflightResult):
                    raise _RunnerFailure("proxy_preflight_failed")
            snapshot["proxy_url"] = preflight.proxy_url
            self._emit(progress, 25)

            remaining = self._remaining(deadline, cancel_event)
            try:
                launch = self._browser_adapter.launch(
                    snapshot,
                    timeout_seconds=remaining,
                    cancel_event=cancel_event,
                )
            except (TimeoutError, DiagnosticBrowserCrashed):
                raise
            except Exception:
                raise DiagnosticBrowserCrashed from None
            if not isinstance(launch, BrowserLaunch):
                raise DiagnosticBrowserCrashed
            self._emit(progress, 45)

            target = self._target_adapter.run(
                launch.session,
                request.target_url,
                timeout_seconds=self._remaining(deadline, cancel_event),
                cancel_event=cancel_event,
                progress=lambda value: self._emit(progress, max(45, min(85, value))),
            )
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
            return DiagnosticResult(
                kind=str(request.kind),
                status=target.status,
                findings=findings,
                error_code=error_code,
                screenshot_path=artifacts.screenshot_path,
                report_path=artifacts.report_path,
            )
        except _Cancelled:
            return DiagnosticResult(
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
            return DiagnosticResult(
                kind=str(request.kind),
                status="failed",
                findings={},
                error_code=code,
                report_path=report_path,
            )
        finally:
            if launch is not None:
                try:
                    launch.session.close()
                except Exception:
                    pass
            if temporary_profile is not None:
                try:
                    shutil.rmtree(temporary_profile)
                except OSError:
                    pass
            if profile_lock is not None:
                try:
                    profile_lock.release()
                except Exception:
                    pass
            if slot_acquired:
                self._semaphore.release()
