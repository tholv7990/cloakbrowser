from __future__ import annotations

import threading
import time

import pytest

from manager_backend.errors import ManagerError
from manager_backend.features.runtime.manager import RuntimeManager
from manager_backend.models import Profile, RuntimeSession


class FakeHandle:
    def __init__(self):
        self.closed = threading.Event()
        self.close_thread = None

    def close(self):
        self.close_thread = threading.get_ident()
        self.closed.set()

    def is_closed(self):
        return self.closed.is_set()


class FakeLauncher:
    def __init__(self):
        self.handles = {}
        self.launch_threads = {}

    def launch(self, snapshot):
        handle = FakeHandle()
        self.handles[snapshot["id"]] = handle
        self.launch_threads[snapshot["id"]] = threading.get_ident()
        return handle


class BlockingLauncher(FakeLauncher):
    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self._lock = threading.Lock()
        self.active = 0
        self.maximum_active = 0

    def launch(self, snapshot):
        with self._lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        self.release.wait(3)
        with self._lock:
            self.active -= 1
        return super().launch(snapshot)


def _profile(session_factory, name):
    with session_factory() as session:
        profile = Profile(
            name=name,
            fingerprint_seed=str(abs(hash(name)) % 1_000_000_000 + 1),
            fingerprint_config_hash="a" * 64,
        )
        session.add(profile)
        session.commit()
        return profile.id


def _wait_state(session_factory, runtime_id, expected, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with session_factory() as session:
            state = session.get(RuntimeSession, runtime_id).state
        if state == expected:
            return
        time.sleep(0.01)
    raise AssertionError(f"runtime did not reach {expected}; last state was {state}")


def test_start_and_stop_keep_launcher_on_worker_thread(db_session_factory, settings):
    launcher = FakeLauncher()
    manager = RuntimeManager(db_session_factory, settings, launcher=launcher)
    profile_id = _profile(db_session_factory, "one")
    runtime = manager.start(profile_id)
    _wait_state(db_session_factory, runtime.id, "running")

    with db_session_factory() as session:
        stored = session.get(RuntimeSession, runtime.id)
        assert stored.manager_instance_id
        assert stored.manager_pid
        assert stored.manager_created_at

    manager.stop(profile_id)
    _wait_state(db_session_factory, runtime.id, "stopped")
    assert launcher.launch_threads[profile_id] == launcher.handles[profile_id].close_thread
    manager.shutdown()


def test_duplicate_start_is_rejected(db_session_factory, settings):
    manager = RuntimeManager(db_session_factory, settings, launcher=FakeLauncher())
    profile_id = _profile(db_session_factory, "duplicate")
    manager.start(profile_id)
    with pytest.raises(ManagerError) as error:
        manager.start(profile_id)
    assert error.value.code == "profile_already_running"
    manager.shutdown()


def test_stop_is_idempotent_for_stopped_profile(db_session_factory, settings):
    manager = RuntimeManager(db_session_factory, settings, launcher=FakeLauncher())
    profile_id = _profile(db_session_factory, "stopped")
    assert manager.stop(profile_id) is None
    manager.shutdown()


def test_launcher_failure_transitions_to_crashed(db_session_factory, settings):
    class BrokenLauncher:
        def launch(self, snapshot):
            raise RuntimeError("raw local path and secret")

    manager = RuntimeManager(db_session_factory, settings, launcher=BrokenLauncher())
    profile_id = _profile(db_session_factory, "broken")
    runtime = manager.start(profile_id)
    _wait_state(db_session_factory, runtime.id, "crashed")
    with db_session_factory() as session:
        stored = session.get(RuntimeSession, runtime.id)
        assert stored.last_message == "browser_launch_failed"
        assert "secret" not in stored.last_message
    manager.shutdown()


def test_launch_queue_limits_concurrent_browser_starts(db_session_factory, settings):
    launcher = BlockingLauncher()
    manager = RuntimeManager(db_session_factory, settings, launcher=launcher)
    runtimes = [
        manager.start(_profile(db_session_factory, f"queued-{number}"))
        for number in range(3)
    ]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and launcher.maximum_active < 2:
        time.sleep(0.01)
    assert launcher.maximum_active == 2
    with db_session_factory() as session:
        states = [session.get(RuntimeSession, runtime.id).state for runtime in runtimes]
    assert states.count("queued") == 1
    launcher.release.set()
    for runtime in runtimes:
        _wait_state(db_session_factory, runtime.id, "running")
    manager.shutdown()


def test_filesystem_lock_failure_does_not_create_runtime(db_session_factory, settings):
    class UnavailableLock:
        def acquire(self):
            raise ManagerError("profile_locked", "This profile is in use.", 409)

        def release(self):
            raise AssertionError("unacquired lock must not be released")

    manager = RuntimeManager(
        db_session_factory,
        settings,
        launcher=FakeLauncher(),
        lock_factory=lambda _profile_id: UnavailableLock(),
    )
    profile_id = _profile(db_session_factory, "locked")
    with pytest.raises(ManagerError) as error:
        manager.start(profile_id)
    assert error.value.code == "profile_locked"
    with db_session_factory() as session:
        assert session.query(RuntimeSession).count() == 0
