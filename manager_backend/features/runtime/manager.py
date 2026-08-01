from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import psutil

from ...config import ManagerSettings
from ...errors import ManagerError
from ...models import Profile, RuntimeSession
from ..profiles.fingerprint_coherence import validate_fingerprint_coherence
from ..profiles.service import get_profile
from .launcher import (
    CloakPersistentLauncher,
    enabled_profile_extension_paths,
    profile_launch_snapshot,
)
from .locks import ProfileFileLock
from .logs import append_profile_log
from .service import create_runtime_session
from .timing import StartTimer
from .worker import ProfileWorker


_COHERENCE_LOGGER = logging.getLogger("manager.runtime.coherence")


def _coherence_profile(profile: Profile) -> dict[str, Any]:
    values = {
        "browser_version_mode": profile.browser_version_mode,
        "browser_version": profile.browser_version,
        "custom_user_agent": (
            profile.custom_user_agent
            if profile.user_agent_mode == "custom"
            else None
        ),
        "gpu_vendor": profile.gpu_vendor,
        "gpu_renderer": profile.gpu_renderer,
        "location": dict(profile.location or {}),
    }
    proxy = profile.proxy
    if (
        proxy is not None
        and proxy.deleted_at is None
        and proxy.last_checked_at is not None
    ):
        values.update(
            proxy_verified=True,
            proxy_country=proxy.country,
            proxy_timezone=proxy.timezone,
        )
    return values


def _preflight_fingerprint_coherence(profile: Profile) -> None:
    result = validate_fingerprint_coherence(_coherence_profile(profile))
    findings = result["findings"]
    if findings:
        _COHERENCE_LOGGER.log(
            logging.ERROR
            if any(finding["severity"] == "error" for finding in findings)
            else logging.WARNING,
            json.dumps(
                {
                    "event": "runtime.fingerprint_coherence",
                    "profile_id": profile.id,
                    "status": result["status"],
                    "finding_codes": [finding["code"] for finding in findings],
                },
                sort_keys=True,
            ),
        )
    if any(finding["severity"] == "error" for finding in findings):
        raise ManagerError(
            "fingerprint_incoherent",
            "Fingerprint settings are incoherent.",
            409,
        )


class RuntimeManager:
    def __init__(
        self,
        session_factory,
        settings: ManagerSettings,
        *,
        launcher=None,
        lock_factory=None,
        proxy_preflight=None,
        proxy_health=None,
        license_gate=None,
    ):
        self._session_factory = session_factory
        self._settings = settings
        self._launcher = launcher or CloakPersistentLauncher()
        self._proxy_preflight = proxy_preflight or (lambda _snapshot: None)
        # Optional mid-session proxy monitor (F-013); None disables it (default).
        self._proxy_health = proxy_health
        # Raises ManagerError if the app isn't entitled to launch; no-op when license
        # enforcement is off (the default), so the free/dev build is unaffected.
        self._license_gate = license_gate or (lambda: None)
        self._instance_id = str(uuid4())
        self._process_id = os.getpid()
        self._process_created_at = datetime.fromtimestamp(
            psutil.Process(self._process_id).create_time(), timezone.utc
        )
        self._lock_factory = lock_factory or (
            lambda profile_id: ProfileFileLock(
                settings.profile_root / profile_id / ".runtime.lock", profile_id
            )
        )
        self._launch_semaphore = threading.BoundedSemaphore(settings.max_concurrent_launches)
        self._workers: dict[str, ProfileWorker] = {}
        self._lock = threading.Lock()

    def _snapshot(self, session, profile: Profile) -> dict[str, Any]:
        extension_paths = enabled_profile_extension_paths(
            session, profile.id, self._settings
        )
        return profile_launch_snapshot(
            profile, self._settings, extension_paths=extension_paths
        )

    def start(self, profile_id: str) -> RuntimeSession:
        # One timer spans the whole start; stage() calls below and in the worker
        # record where the wall-clock goes (logged as runtime.start_timing).
        timer = StartTimer()
        # License gate first: a revoked/expired key blocks the launch before any work.
        self._license_gate()
        with self._lock:
            existing = self._workers.get(profile_id)
            if existing is not None and existing.is_alive():
                raise ManagerError(
                    "profile_already_running", "This profile is already active.", 409
                )
            profile_lock = self._lock_factory(profile_id)
            with timer.stage("lock_acquire"):
                profile_lock.acquire()
            try:
                with self._session_factory() as session:
                    with timer.stage("profile_load"):
                        profile = get_profile(session, profile_id)
                        snapshot = self._snapshot(session, profile)
                        _preflight_fingerprint_coherence(profile)
                    with timer.stage("session_create"):
                        runtime = create_runtime_session(session, profile)
                        runtime.manager_instance_id = self._instance_id
                        runtime.manager_pid = self._process_id
                        runtime.manager_created_at = self._process_created_at
                        session.commit()
                        session.refresh(runtime)
                        append_profile_log(
                            session,
                            profile.id,
                            "info",
                            "runtime.start_requested",
                            settings=self._settings,
                        )
                        runtime_id = runtime.id
            except Exception:
                profile_lock.release()
                raise
            worker = ProfileWorker(
                runtime_id=runtime_id,
                snapshot=snapshot,
                session_factory=self._session_factory,
                launcher=self._launcher,
                launch_semaphore=self._launch_semaphore,
                profile_lock=profile_lock,
                proxy_preflight=self._proxy_preflight,
                proxy_health=self._proxy_health,
                on_finished=self._worker_finished,
                settings=self._settings,
                timer=timer,
            )
            self._workers[profile_id] = worker
            worker.start()
            return runtime

    def stop(self, profile_id: str) -> RuntimeSession | None:
        with self._lock:
            worker = self._workers.get(profile_id)
        if worker is None or not worker.is_alive():
            return None
        with self._session_factory() as session:
            append_profile_log(
                session,
                profile_id,
                "info",
                "runtime.stop_requested",
                settings=self._settings,
            )
        worker.request_stop()
        with self._session_factory() as session:
            return session.get(RuntimeSession, worker.runtime_id)

    def _worker_finished(self, profile_id: str, worker: ProfileWorker) -> None:
        with self._lock:
            if self._workers.get(profile_id) is worker:
                self._workers.pop(profile_id, None)

    def shutdown(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            worker.request_stop()
        for worker in workers:
            worker.join(timeout=10)
