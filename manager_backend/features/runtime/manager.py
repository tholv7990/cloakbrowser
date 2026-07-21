from __future__ import annotations

import threading
from typing import Any

from ...config import ManagerSettings
from ...errors import ManagerError
from ...models import Profile, RuntimeSession
from ..profiles.service import get_profile
from .launcher import CloakPersistentLauncher
from .locks import ProfileFileLock
from .service import create_runtime_session
from .worker import ProfileWorker


class RuntimeManager:
    def __init__(
        self,
        session_factory,
        settings: ManagerSettings,
        *,
        launcher=None,
        lock_factory=None,
    ):
        self._session_factory = session_factory
        self._settings = settings
        self._launcher = launcher or CloakPersistentLauncher()
        self._lock_factory = lock_factory or (
            lambda profile_id: ProfileFileLock(settings.profile_root / profile_id / ".runtime.lock")
        )
        self._launch_semaphore = threading.BoundedSemaphore(settings.max_concurrent_launches)
        self._workers: dict[str, ProfileWorker] = {}
        self._lock = threading.Lock()

    def _snapshot(self, profile: Profile) -> dict[str, Any]:
        location = profile.location or {}
        return {
            "id": profile.id,
            "profile_dir": self._settings.profile_root / profile.id,
            "fingerprint_seed": profile.fingerprint_seed,
            "fingerprint_preset": profile.fingerprint_preset,
            "browser_version": (
                profile.browser_version if profile.browser_version_mode == "pinned" else None
            ),
            "custom_user_agent": (
                profile.custom_user_agent if profile.user_agent_mode == "custom" else None
            ),
            "locale": location.get("locale"),
            "timezone": location.get("timezone"),
            "startup_urls": list(profile.startup_urls or []),
        }

    def start(self, profile_id: str) -> RuntimeSession:
        with self._lock:
            existing = self._workers.get(profile_id)
            if existing is not None and existing.is_alive():
                raise ManagerError(
                    "profile_already_running", "This profile is already active.", 409
                )
            profile_lock = self._lock_factory(profile_id)
            profile_lock.acquire()
            try:
                with self._session_factory() as session:
                    profile = get_profile(session, profile_id)
                    runtime = create_runtime_session(session, profile)
                    snapshot = self._snapshot(profile)
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
                on_finished=self._worker_finished,
            )
            self._workers[profile_id] = worker
            worker.start()
            return runtime

    def stop(self, profile_id: str) -> RuntimeSession | None:
        with self._lock:
            worker = self._workers.get(profile_id)
        if worker is None or not worker.is_alive():
            return None
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
