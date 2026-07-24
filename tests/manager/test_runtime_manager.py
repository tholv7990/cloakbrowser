from __future__ import annotations

import json
import threading
import time

import pytest

from manager_backend.errors import ManagerError
from manager_backend.features.extensions import service as extension_service
from manager_backend.features.runtime.launcher import (
    persistent_context_kwargs,
    profile_launch_snapshot,
)
from manager_backend.features.runtime.manager import RuntimeManager
from manager_backend.models import Extension, Profile, RuntimeSession


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
        self.snapshots = {}

    def launch(self, snapshot):
        handle = FakeHandle()
        self.handles[snapshot["id"]] = handle
        self.launch_threads[snapshot["id"]] = threading.get_ident()
        self.snapshots[snapshot["id"]] = dict(snapshot)
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


def _register_extension(
    session_factory,
    settings,
    profile_id,
    directory,
    *,
    name,
    enabled=True,
    assigned=True,
):
    directory.mkdir()
    (directory / "manifest.json").write_text(
        json.dumps({"manifest_version": 3, "name": name, "version": "1"}),
        encoding="utf-8",
    )
    with session_factory() as session:
        extension, _created = extension_service.register_extension(
            session, settings, str(directory)
        )
        extension.enabled = enabled
        if assigned:
            profile = session.get(Profile, profile_id)
            profile.extensions.append(extension)
        session.commit()
        return extension.id


def test_launch_builder_uses_structured_extension_option_not_chromium_arguments():
    extension_paths = [r"C:\extensions\one;not-a-command", r"C:\extensions\two"]
    kwargs = persistent_context_kwargs(
        {
            "fingerprint_seed": "42",
            "fingerprint_preset": "consistent",
            "extension_paths": extension_paths,
            "args": ["--fingerprint=999", r"--load-extension=C:\unmanaged"],
        },
        headless=False,
    )

    assert kwargs["extension_paths"] == extension_paths
    assert isinstance(kwargs["extension_paths"], list)
    assert kwargs["args"] == [
        "--fingerprint=42",
        "--window-size=1920,1080",
        "--remote-debugging-port=0",  # input-sync CDP endpoint (headed only)
    ]
    assert all("load-extension" not in argument for argument in kwargs["args"])


def test_launch_builder_uses_preflight_exit_ip_for_webrtc_without_auto_lookup():
    kwargs = persistent_context_kwargs(
        {
            "fingerprint_seed": "42",
            "fingerprint_preset": "consistent",
            "proxy_url": "socks5://proxy.example:1080",
            "proxy_exit_ip": "203.0.113.8",
            "location": {"webrtc_mode": "proxy"},
        },
        headless=False,
    )

    assert "--fingerprint-webrtc-ip=203.0.113.8" in kwargs["args"]
    assert "--fingerprint-webrtc-ip=auto" not in kwargs["args"]


def test_start_passes_only_enabled_assigned_extensions_in_deterministic_order(
    db_session_factory, settings, tmp_path, monkeypatch
):
    monkeypatch.setattr(extension_service, "_temporary_roots", lambda: ())
    launcher = FakeLauncher()
    manager = RuntimeManager(db_session_factory, settings, launcher=launcher)
    profile_id = _profile(db_session_factory, "extensions")
    z_path = tmp_path / "z-extension"
    a_path = tmp_path / "a-extension"
    _register_extension(
        db_session_factory, settings, profile_id, z_path, name="Zulu"
    )
    _register_extension(
        db_session_factory, settings, profile_id, a_path, name="Alpha"
    )
    _register_extension(
        db_session_factory,
        settings,
        profile_id,
        tmp_path / "disabled",
        name="Disabled",
        enabled=False,
    )
    _register_extension(
        db_session_factory,
        settings,
        profile_id,
        tmp_path / "unassigned",
        name="Unassigned",
        assigned=False,
    )

    runtime = manager.start(profile_id)
    _wait_state(db_session_factory, runtime.id, "running")

    assert launcher.snapshots[profile_id]["extension_paths"] == [
        str(a_path.resolve()),
        str(z_path.resolve()),
    ]
    manager.shutdown()


def test_start_omits_extension_unregistered_after_assignment(
    db_session_factory, settings, tmp_path, monkeypatch
):
    monkeypatch.setattr(extension_service, "_temporary_roots", lambda: ())
    launcher = FakeLauncher()
    manager = RuntimeManager(db_session_factory, settings, launcher=launcher)
    profile_id = _profile(db_session_factory, "unregistered-extension")
    extension_id = _register_extension(
        db_session_factory,
        settings,
        profile_id,
        tmp_path / "removed",
        name="Removed",
    )
    with db_session_factory() as session:
        extension_service.unregister_extension(session, extension_id)

    runtime = manager.start(profile_id)
    _wait_state(db_session_factory, runtime.id, "running")

    assert launcher.snapshots[profile_id]["extension_paths"] == []
    manager.shutdown()


def test_start_revalidates_registered_extension_before_creating_runtime(
    db_session_factory, settings, tmp_path, monkeypatch
):
    monkeypatch.setattr(extension_service, "_temporary_roots", lambda: ())
    launcher = FakeLauncher()
    manager = RuntimeManager(db_session_factory, settings, launcher=launcher)
    profile_id = _profile(db_session_factory, "changed-extension")
    directory = tmp_path / "changed"
    _register_extension(
        db_session_factory, settings, profile_id, directory, name="Original"
    )
    (directory / "manifest.json").write_text(
        json.dumps({"manifest_version": 3, "name": "Changed", "version": "2"}),
        encoding="utf-8",
    )

    with pytest.raises(ManagerError) as caught:
        manager.start(profile_id)

    assert caught.value.code == "extension_manifest_changed"
    assert str(directory) not in caught.value.message
    assert launcher.snapshots == {}
    with db_session_factory() as session:
        assert session.query(RuntimeSession).count() == 0

    with db_session_factory() as session:
        extension = session.query(Profile).filter_by(id=profile_id).one().extensions[0]
        extension.enabled = False
        session.commit()
    runtime = manager.start(profile_id)
    _wait_state(db_session_factory, runtime.id, "running")
    manager.shutdown()


def test_start_rejects_legacy_comma_delimited_extension_assignment(
    db_session_factory, settings, tmp_path, monkeypatch
):
    monkeypatch.setattr(extension_service, "_temporary_roots", lambda: ())
    launcher = FakeLauncher()
    manager = RuntimeManager(db_session_factory, settings, launcher=launcher)
    profile_id = _profile(db_session_factory, "legacy-comma-extension")
    directory = tmp_path / "legacy,ambiguous"
    directory.mkdir()
    raw_manifest = json.dumps(
        {"manifest_version": 3, "name": "Legacy", "version": "1"}
    ).encode("utf-8")
    (directory / "manifest.json").write_bytes(raw_manifest)
    metadata = extension_service._manifest_metadata(raw_manifest)
    with db_session_factory() as session:
        extension = Extension(
            directory=str(directory.resolve()),
            name=metadata.name,
            version=metadata.version,
            description=metadata.description,
            manifest_version=metadata.manifest_version,
            permissions=metadata.permissions,
            manifest_hash=metadata.manifest_hash,
        )
        profile = session.get(Profile, profile_id)
        profile.extensions.append(extension)
        session.commit()

    with pytest.raises(ManagerError) as caught:
        manager.start(profile_id)

    assert caught.value.code == "extension_path_forbidden"
    assert str(directory) not in caught.value.message
    assert launcher.snapshots == {}
    with db_session_factory() as session:
        assert session.query(RuntimeSession).count() == 0


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


# --- P3: immediate browser-close (process-exit watcher) -----------------------


class WatchableHandle:
    """A handle whose OS-poll is.closed() NEVER fires on its own — only an
    explicit close() or the process-exit watcher (wait_until_closed) can finalize
    it. This isolates the immediate-close path from the polling fallback."""

    def __init__(self):
        self._exit = threading.Event()  # "the browser process has exited"
        self._closed = threading.Event()  # explicit close() was called
        self.close_calls = 0

    def wait_until_closed(self) -> None:
        self._exit.wait()

    def is_closed(self) -> bool:
        # The poll only reports closed after an explicit close(); it never detects
        # the process exit on its own, so a passing test proves the watcher works.
        return self._closed.is_set()

    def close(self) -> None:
        self.close_calls += 1
        self._closed.set()
        self._exit.set()  # a real close() ends the process, unblocking the watcher

    def signal_process_exit(self) -> None:
        self._exit.set()


class WatchableLauncher(FakeLauncher):
    def launch(self, snapshot):
        handle = WatchableHandle()
        self.handles[snapshot["id"]] = handle
        return handle


class CountingLock:
    """Wraps the real file lock to count release() calls (must be exactly 1)."""

    def __init__(self, inner):
        self._inner = inner
        self.releases = 0

    def acquire(self) -> None:
        self._inner.acquire()

    def release(self) -> None:
        self.releases += 1
        self._inner.release()


def test_process_exit_watcher_finalizes_without_poll(db_session_factory, settings):
    # is_closed() never reports closed on its own here, so the ONLY way this run
    # can reach "stopped" is the immediate process-exit watcher. Fails (times out)
    # until the watcher exists.
    launcher = WatchableLauncher()
    manager = RuntimeManager(
        db_session_factory, settings, launcher=launcher, proxy_preflight=lambda _s: None
    )
    profile_id = _profile(db_session_factory, "watched")
    runtime = manager.start(profile_id)
    _wait_state(db_session_factory, runtime.id, "running")

    launcher.handles[profile_id].signal_process_exit()

    _wait_state(db_session_factory, runtime.id, "stopped", timeout=3)
    manager.shutdown()


def test_stop_during_process_exit_finalizes_once_and_frees_lock(
    db_session_factory, settings
):
    # Race: the browser exits at the same moment an explicit stop arrives. The run
    # must finalize exactly once (one lock release) and leave the profile
    # relaunchable (lock freed, no stuck state).
    from manager_backend.features.runtime.locks import ProfileFileLock

    locks: list[CountingLock] = []

    def lock_factory(profile_id: str) -> CountingLock:
        lock = CountingLock(
            ProfileFileLock(
                settings.profile_root / profile_id / ".runtime.lock", profile_id
            )
        )
        locks.append(lock)
        return lock

    launcher = WatchableLauncher()
    manager = RuntimeManager(
        db_session_factory,
        settings,
        launcher=launcher,
        lock_factory=lock_factory,
        proxy_preflight=lambda _s: None,
    )
    profile_id = _profile(db_session_factory, "race")
    runtime = manager.start(profile_id)
    _wait_state(db_session_factory, runtime.id, "running")

    # Fire both signals as close together as possible.
    launcher.handles[profile_id].signal_process_exit()
    manager.stop(profile_id)

    _wait_state(db_session_factory, runtime.id, "stopped", timeout=3)
    # The lock release runs in the worker's finally, just after the stopped
    # transition — wait for it, then assert it happened exactly once (idempotent,
    # no double release from the stop+exit race).
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and locks[0].releases == 0:
        time.sleep(0.01)
    assert locks[0].releases == 1
    # Lock is free — the profile can be started again immediately.
    second = manager.start(profile_id)
    _wait_state(db_session_factory, second.id, "running")
    manager.shutdown()
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


def test_slow_proxy_preflight_does_not_consume_browser_launch_slot(
    db_session_factory, settings
):
    first_profile = _profile(db_session_factory, "slow-preflight")
    second_profile = _profile(db_session_factory, "fast-preflight")
    first_entered = threading.Event()
    release_first = threading.Event()

    def preflight(snapshot):
        if snapshot["id"] == first_profile:
            first_entered.set()
            release_first.wait(3)
        return None

    launcher = FakeLauncher()
    manager = RuntimeManager(
        db_session_factory,
        settings.model_copy(update={"max_concurrent_launches": 1}),
        launcher=launcher,
        proxy_preflight=preflight,
    )
    first_runtime = manager.start(first_profile)
    assert first_entered.wait(1)
    second_runtime = manager.start(second_profile)

    _wait_state(db_session_factory, second_runtime.id, "running", timeout=1)
    assert first_profile not in launcher.handles
    release_first.set()
    _wait_state(db_session_factory, first_runtime.id, "running")
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


def test_proxy_preflight_failure_blocks_browser_launch(db_session_factory, settings):
    launcher = FakeLauncher()

    def reject(_snapshot):
        raise ManagerError("proxy_preflight_failed", "The assigned proxy is unavailable.", 409)

    manager = RuntimeManager(
        db_session_factory,
        settings,
        launcher=launcher,
        proxy_preflight=reject,
    )
    profile_id = _profile(db_session_factory, "proxy-blocked")
    runtime = manager.start(profile_id)
    _wait_state(db_session_factory, runtime.id, "crashed")
    assert profile_id not in launcher.handles
    with db_session_factory() as session:
        assert session.get(RuntimeSession, runtime.id).last_message == "proxy_preflight_failed"


def test_proxy_death_midsession_is_surfaced(db_session_factory, settings, monkeypatch):
    # F-013: if the proxy dies mid-session, the run must not silently continue —
    # repeated health failures crash the runtime with a safe reason code.
    from manager_backend.features.runtime.worker import ProfileWorker

    monkeypatch.setattr(ProfileWorker, "_PROXY_HEALTH_INTERVAL", 0.0)
    monkeypatch.setattr(ProfileWorker, "_PROXY_HEALTH_FAILURES", 1)
    launcher = FakeLauncher()
    manager = RuntimeManager(
        db_session_factory,
        settings,
        launcher=launcher,
        proxy_preflight=lambda _snapshot: "socks5://proxy.example:1080",
        proxy_health=lambda _snapshot: False,
    )
    profile_id = _profile(db_session_factory, "proxy-death")
    runtime = manager.start(profile_id)
    _wait_state(db_session_factory, runtime.id, "crashed")
    with db_session_factory() as session:
        assert session.get(RuntimeSession, runtime.id).last_message == "proxy_lost"
    manager.shutdown()


def test_proxy_preflight_value_is_forwarded_only_in_worker_memory(
    db_session_factory, settings
):
    launcher = FakeLauncher()
    manager = RuntimeManager(
        db_session_factory,
        settings,
        launcher=launcher,
        proxy_preflight=lambda _snapshot: "socks5://alice:secret@proxy.example:1080",
    )
    profile_id = _profile(db_session_factory, "proxy-forwarded")
    runtime = manager.start(profile_id)
    _wait_state(db_session_factory, runtime.id, "running")
    assert launcher.handles[profile_id]
    assert launcher.snapshots[profile_id]["proxy_url"].endswith("@proxy.example:1080")
    manager.shutdown()


def test_launch_snapshot_carries_profile_proxy_check_toggle(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory, "proxy-toggle")
    with db_session_factory() as session:
        profile = session.get(Profile, profile_id)
        profile.test_proxy_before_launch = False
        session.commit()
        snapshot = profile_launch_snapshot(profile, settings)

    assert snapshot["test_proxy_before_launch"] is False


def test_start_emits_structured_stage_timing(db_session_factory, settings):
    # The start path emits one non-secret runtime.start_timing line breaking the
    # wall-clock into stages so we can see where a slow start (e.g. proxy
    # preflight) actually spends its time. Capture via a handler attached DIRECTLY
    # to the timing logger (not caplog's root propagation, which other tests in the
    # full suite can disturb) and force it enabled for the duration.
    import logging

    captured: list[str] = []

    class _Sink(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    logger = logging.getLogger("manager.runtime.timing")
    sink = _Sink()
    prev_level, prev_disabled = logger.level, logger.disabled
    prev_global_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)  # undo any leaked global logging.disable()
    logger.addHandler(sink)
    logger.setLevel(logging.INFO)
    logger.disabled = False
    try:
        launcher = FakeLauncher()
        manager = RuntimeManager(
            db_session_factory,
            settings,
            launcher=launcher,
            proxy_preflight=lambda _snapshot: None,
        )
        profile_id = _profile(db_session_factory, "timed-start")
        runtime = manager.start(profile_id)
        _wait_state(db_session_factory, runtime.id, "running")
        # The emit fires just after the running transition, on the worker thread.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not any(
            "runtime.start_timing" in message for message in captured
        ):
            time.sleep(0.01)
        manager.shutdown()
    finally:
        logger.removeHandler(sink)
        logger.setLevel(prev_level)
        logger.disabled = prev_disabled
        logging.disable(prev_global_disable)

    timings = [
        json.loads(message) for message in captured if "runtime.start_timing" in message
    ]
    assert timings, "no runtime.start_timing line was emitted"
    payload = timings[-1]
    assert payload["event"] == "runtime.start_timing"
    assert payload["profile_id"] == profile_id
    stages = payload["stages_ms"]
    for stage in (
        "lock_acquire",
        "profile_load",
        "session_create",
        "proxy_preflight",
        "launch_gate_wait",
        "browser_launch",
    ):
        assert stage in stages, f"missing timing stage: {stage}"
        assert isinstance(stages[stage], int) and stages[stage] >= 0
    assert isinstance(payload["total_ms"], int) and payload["total_ms"] >= 0
    # profile_id must be the canonical id and nothing secret should appear.
    assert set(payload) == {"event", "profile_id", "stages_ms", "total_ms"}
