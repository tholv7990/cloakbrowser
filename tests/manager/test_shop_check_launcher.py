"""RuntimeManagerLauncher waits for real runtime readiness + a CDP endpoint.

RuntimeManager.start() returns immediately while Chromium boots in a background
worker; Shop-check must block until the runtime is `running` AND its CDP
endpoint is persisted before it drives the page. On any failure the launcher
must stop whatever it started (no orphaned browser).
"""

from __future__ import annotations

import threading
import time

import pytest

from manager_backend.features.shop_check.launcher import (
    RuntimeLaunchError,
    RuntimeManagerLauncher,
)
from manager_backend.models import Profile, RuntimeSession


class FakeRuntimeManager:
    """Models RuntimeManager.start()'s async readiness: it inserts a `starting`
    runtime row and (optionally) flips it to a terminal state after a delay,
    exactly like the real background worker."""

    def __init__(self, session_factory, *, becomes, endpoint=None, delay=0.05):
        self._session_factory = session_factory
        self._becomes = becomes  # 'running' | 'crashed' | 'never'
        self._endpoint = endpoint
        self._delay = delay
        self.stopped: list[str] = []

    def start(self, profile_id):
        with self._session_factory() as session:
            session.add(Profile(id=profile_id, name=profile_id,
                                fingerprint_seed=profile_id, fingerprint_config_hash="0" * 64))
            runtime = RuntimeSession(profile_id=profile_id, state="starting", last_message="starting")
            session.add(runtime)
            session.commit()
            runtime_id = runtime.id
        if self._becomes != "never":
            threading.Thread(target=self._flip, args=(runtime_id,), daemon=True).start()
        with self._session_factory() as session:
            return session.get(RuntimeSession, runtime_id)

    def _flip(self, runtime_id):
        time.sleep(self._delay)
        with self._session_factory() as session:
            runtime = session.get(RuntimeSession, runtime_id)
            if self._becomes == "running":
                runtime.state = "running"
                runtime.cdp_endpoint = self._endpoint
            else:
                runtime.state = "crashed"
                runtime.last_message = "proxy_preflight_failed"
            session.commit()

    def stop(self, profile_id):
        self.stopped.append(profile_id)


def test_returns_endpoint_once_runtime_is_running(db_session_factory):
    manager = FakeRuntimeManager(
        db_session_factory, becomes="running", endpoint="http://127.0.0.1:9222"
    )
    launcher = RuntimeManagerLauncher(manager, db_session_factory)
    endpoint = launcher.start_and_wait_ready(
        "prof-1", timeout_seconds=5, is_cancelled=lambda: False
    )
    assert endpoint == "http://127.0.0.1:9222"


def test_raises_and_stops_when_runtime_crashes(db_session_factory):
    manager = FakeRuntimeManager(db_session_factory, becomes="crashed")
    launcher = RuntimeManagerLauncher(manager, db_session_factory)
    with pytest.raises(RuntimeLaunchError):
        launcher.start_and_wait_ready("prof-2", timeout_seconds=5, is_cancelled=lambda: False)
    assert manager.stopped == ["prof-2"]  # cleaned up, no orphan browser


def test_times_out_and_stops_when_never_ready(db_session_factory):
    manager = FakeRuntimeManager(db_session_factory, becomes="never")
    launcher = RuntimeManagerLauncher(manager, db_session_factory)
    with pytest.raises(RuntimeLaunchError):
        launcher.start_and_wait_ready("prof-3", timeout_seconds=0.3, is_cancelled=lambda: False)
    assert manager.stopped == ["prof-3"]


def test_cancel_aborts_the_wait_and_stops(db_session_factory):
    manager = FakeRuntimeManager(db_session_factory, becomes="never")
    launcher = RuntimeManagerLauncher(manager, db_session_factory)
    with pytest.raises(RuntimeLaunchError):
        launcher.start_and_wait_ready("prof-4", timeout_seconds=5, is_cancelled=lambda: True)
    assert manager.stopped == ["prof-4"]


def test_running_without_an_endpoint_is_not_ready(db_session_factory):
    # A running runtime whose DevToolsActivePort never appeared can't be driven.
    manager = FakeRuntimeManager(db_session_factory, becomes="running", endpoint=None)
    launcher = RuntimeManagerLauncher(manager, db_session_factory)
    with pytest.raises(RuntimeLaunchError):
        launcher.start_and_wait_ready("prof-5", timeout_seconds=0.3, is_cancelled=lambda: False)
    assert manager.stopped == ["prof-5"]
