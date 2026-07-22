from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from manager_backend.features.diagnostics import artifacts as artifacts_module
from manager_backend.features.diagnostics import runner as runner_module
from manager_backend.config import ManagerSettings
from manager_backend.features.diagnostics.artifacts import (
    ArtifactBoundaryError,
    write_diagnostic_artifacts,
)
from manager_backend.features.diagnostics.runner import (
    BrowserLaunch,
    DiagnosticBrowserCrashed,
    DiagnosticNetworkError,
    DiagnosticRequest,
    DiagnosticRunner,
    ProxyPreflightResult,
    TargetResult,
)
from manager_backend.features.runtime.launcher import profile_launch_snapshot
from manager_backend.models import Profile, RuntimeSession


PNG = b"\x89PNG\r\n\x1a\nlocal-fixture-image"


class FakeSession:
    def __init__(
        self,
        *,
        tier: str = "team",
        version: str = "136.0.1.2",
        close_error: Exception | None = None,
        terminate_error: Exception | None = None,
    ):
        self.tier = tier
        self.version = version
        self.closed = False
        self.close_error = close_error
        self.terminate_error = terminate_error
        self.terminate_calls = 0
        self.close_thread = None

    def close(self) -> None:
        self.close_thread = threading.get_ident()
        if self.close_error is not None:
            raise self.close_error
        self.closed = True

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self.terminate_error is not None:
            raise self.terminate_error
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed


class HangingCleanupSession(FakeSession):
    def __init__(self, hang: str):
        super().__init__(close_error=RuntimeError("raw close"))
        self.hang = hang
        self.cleanup_entered = threading.Event()
        self.cleanup_release = threading.Event()

    def is_closed(self) -> bool:
        if self.hang == "is_closed" and not self.cleanup_release.is_set():
            self.cleanup_entered.set()
            self.cleanup_release.wait()
        return self.closed

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self.hang == "terminate" and not self.cleanup_release.is_set():
            self.cleanup_entered.set()
            self.cleanup_release.wait()
        self.closed = True


class FakeBrowserAdapter:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        session_factory=FakeSession,
        delay: float = 0,
    ):
        self.error = error
        self.session_factory = session_factory
        self.delay = delay
        self.launches: list[dict] = []
        self.sessions: list[FakeSession] = []
        self.launch_threads: list[int] = []

    def launch(self, snapshot, *, timeout_seconds, cancel_event):
        self.launch_threads.append(threading.get_ident())
        self.launches.append(dict(snapshot))
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        session = self.session_factory()
        self.sessions.append(session)
        return BrowserLaunch(session=session, tier=session.tier, version=session.version)


class FakeTargetAdapter:
    def __init__(self, action=None):
        self.action = action or self._success
        self.calls: list[tuple[FakeSession, str, float]] = []
        self.call_threads: list[int] = []

    @staticmethod
    def _success(_session, target_url, **_kwargs):
        return TargetResult(
            status="passed",
            findings={"page_loaded": True, "captcha_detected": False},
            final_url=target_url,
            title="Local fixture",
            screenshot=PNG,
        )

    def run(self, session, target_url, *, timeout_seconds, cancel_event, progress):
        self.call_threads.append(threading.get_ident())
        self.calls.append((session, target_url, timeout_seconds))
        return self.action(
            session,
            target_url,
            timeout_seconds=timeout_seconds,
            cancel_event=cancel_event,
            progress=progress,
        )


class FakeLock:
    def __init__(self):
        self.acquired = False
        self.released = False

    def acquire(self):
        self.acquired = True

    def release(self):
        self.released = True


def _settings(settings, **updates) -> ManagerSettings:
    return settings.model_copy(
        update={
            "max_concurrent_diagnostics": 2,
            "diagnostic_timeout_seconds": 1.0,
            **updates,
        }
    )


def _request(*, kind="direct_google_control", profile_id=None, target_url=None):
    targets = {
        "direct_google_control": "https://www.google.com/search?q=CloakBrowser+diagnostic",
        "pixelscan": "https://pixelscan.net/",
        "iphey": "https://iphey.com/",
        "cloudflare": "https://challenge.cloudflare.com/turnstile/v0/generic/",
        "google_search": "https://www.google.com/search?q=CloakBrowser+browser+diagnostic",
    }
    return DiagnosticRequest(
        run_id=str(uuid4()),
        kind=kind,
        profile_id=profile_id,
        target_url=target_url or targets[kind],
    )


def _profile(
    session_factory, *, name="diagnostic", proxy_id=None, startup_urls=None
) -> str:
    with session_factory() as session:
        profile = Profile(
            name=name,
            fingerprint_seed=str(int(uuid4().hex[:12], 16)),
            fingerprint_preset="consistent",
            fingerprint_revision=7,
            fingerprint_config_hash="a" * 64,
            browser_version_mode="pinned",
            browser_version="135.0.0.1",
            user_agent_mode="custom",
            custom_user_agent="FixtureAgent/1.0",
            startup_urls=startup_urls or [],
            location={
                "geo_mode": "proxy",
                "locale": "vi-VN",
                "timezone": "Asia/Ho_Chi_Minh",
                "webrtc_mode": "proxy",
                "geolocation_mode": "proxy",
            },
            window={
                "mode": "custom",
                "width": 1440,
                "height": 900,
                "color_scheme": "dark",
            },
            behavior={
                "humanize_enabled": True,
                "humanize_preset": "careful",
                "restore_previous_tabs": False,
                "ignore_https_errors": False,
            },
            proxy_id=proxy_id,
        )
        session.add(profile)
        session.commit()
        return profile.id


def _runner(
    session_factory,
    settings,
    *,
    browser=None,
    target=None,
    proxy_preflight=None,
    lock_factory=None,
    deferred_result=None,
):
    return DiagnosticRunner(
        session_factory,
        settings,
        browser_adapter=browser or FakeBrowserAdapter(),
        target_adapter=target or FakeTargetAdapter(),
        proxy_preflight=proxy_preflight
        or (lambda _snapshot: ProxyPreflightResult()),
        lock_factory=lock_factory or (lambda _profile_id: FakeLock()),
        **(
            {"deferred_result": deferred_result}
            if deferred_result is not None
            else {}
        ),
    )


def test_profile_diagnostic_requires_stopped_profile(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)
    with db_session_factory() as session:
        session.add(RuntimeSession(profile_id=profile_id, state="running"))
        session.commit()
    browser = FakeBrowserAdapter()
    lock = FakeLock()
    runner = _runner(
        db_session_factory,
        _settings(settings),
        browser=browser,
        lock_factory=lambda _profile_id: lock,
    )

    result = runner.run(
        _request(kind="pixelscan", profile_id=profile_id),
        threading.Event(),
        lambda _value: None,
    )

    assert result.status == "failed"
    assert result.error_code == "profile_not_stopped"
    assert browser.launches == []
    assert lock.acquired and lock.released


def test_profile_diagnostic_reuses_the_exact_normal_launch_snapshot(
    db_session_factory, settings, monkeypatch
):
    profile_id = _profile(db_session_factory)
    extension_paths = [r"C:\extensions\alpha", r"C:\extensions\zulu"]
    monkeypatch.setattr(
        "manager_backend.features.diagnostics.runner.enabled_profile_extension_paths",
        lambda _session, _profile_id, _settings: extension_paths,
    )
    preflight_calls = []

    def preflight(snapshot):
        preflight_calls.append(dict(snapshot))
        return ProxyPreflightResult(
            proxy_url="socks5://alice:secret@proxy.example:1080",
            checked_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
            classification="residential",
        )

    browser = FakeBrowserAdapter()
    runner = _runner(
        db_session_factory,
        _settings(settings),
        browser=browser,
        proxy_preflight=preflight,
    )

    request = _request(kind="pixelscan", profile_id=profile_id)
    result = runner.run(request, threading.Event(), lambda _value: None)

    with db_session_factory() as session:
        profile = session.get(Profile, profile_id)
        expected = profile_launch_snapshot(
            profile, settings, extension_paths=extension_paths
        )
    assert result.status == "passed"
    assert preflight_calls == [expected]
    assert browser.launches == [
        {**expected, "proxy_url": "socks5://alice:secret@proxy.example:1080"}
    ]
    assert browser.launches[0]["location"] == expected["location"]
    assert browser.launches[0]["window"] == expected["window"]
    assert browser.launches[0]["behavior"] == expected["behavior"]
    report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
    assert report["profile"] == {
        "fingerprint_revision": 7,
        "fingerprint_config_hash": "a" * 64,
    }
    assert report["proxy"] == {
        "checked_at": "2026-07-22T00:00:00Z",
        "classification": "residential",
    }
    assert "secret" not in json.dumps(report)


def test_profile_diagnostic_suppresses_normal_startup_urls_and_targets_only_allowlist(
    db_session_factory, settings
):
    profile_id = _profile(
        db_session_factory,
        startup_urls=["https://startup.example/", "http://internal.example/"],
    )
    browser = FakeBrowserAdapter()
    target = FakeTargetAdapter()
    runner = _runner(
        db_session_factory, _settings(settings), browser=browser, target=target
    )
    request = _request(kind="pixelscan", profile_id=profile_id)

    result = runner.run(request, threading.Event(), lambda _value: None)

    assert result.status == "passed"
    assert browser.launches[0]["startup_urls"] == []
    assert [call[1] for call in target.calls] == [request.target_url]


def test_sync_browser_lifecycle_stays_on_one_owner_thread(
    db_session_factory, settings
):
    browser = FakeBrowserAdapter()
    target = FakeTargetAdapter()
    runner = _runner(
        db_session_factory, _settings(settings), browser=browser, target=target
    )

    result = runner.run(_request(), threading.Event(), lambda _value: None)

    assert result.status == "passed"
    assert browser.launch_threads == target.call_threads
    assert browser.sessions[0].close_thread == browser.launch_threads[0]


@pytest.mark.parametrize("stage", ["preflight", "browser", "target"])
def test_total_deadline_rejects_non_cooperative_synchronous_adapters(
    db_session_factory, settings, stage
):
    profile_id = _profile(db_session_factory) if stage == "preflight" else None
    browser = FakeBrowserAdapter(delay=0.2 if stage == "browser" else 0)

    def preflight(_snapshot):
        if stage == "preflight":
            time.sleep(0.2)
        return ProxyPreflightResult()

    def target_action(_session, target_url, **_kwargs):
        if stage == "target":
            time.sleep(0.2)
        return TargetResult(
            status="passed",
            findings={"page_loaded": True},
            final_url=target_url,
            title="late fixture",
            screenshot=PNG,
        )

    runner = _runner(
        db_session_factory,
        _settings(settings, diagnostic_timeout_seconds=0.05),
        browser=browser,
        target=FakeTargetAdapter(target_action),
        proxy_preflight=preflight,
    )
    request = (
        _request(kind="pixelscan", profile_id=profile_id)
        if profile_id
        else _request()
    )

    started = time.monotonic()
    result = runner.run(request, threading.Event(), lambda _value: None)
    elapsed = time.monotonic() - started

    assert result.status == "failed"
    assert result.error_code == "timeout"
    assert elapsed < 0.15
    time.sleep(0.2)
    assert not any(
        thread.name.startswith("diagnostic-adapter-")
        for thread in threading.enumerate()
    )
    assert all(session.closed for session in browser.sessions)
    if stage == "browser":
        assert browser.launches
        assert not Path(browser.launches[0]["profile_dir"]).exists()
        assert runner._semaphore.acquire(timeout=0.05)
        runner._semaphore.release()


def test_late_profile_browser_launch_retains_lock_until_verified_cleanup(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)
    browser = FakeBrowserAdapter(delay=0.2)
    lock = FakeLock()
    runner = _runner(
        db_session_factory,
        _settings(
            settings,
            diagnostic_timeout_seconds=0.05,
            max_concurrent_diagnostics=1,
        ),
        browser=browser,
        lock_factory=lambda _profile_id: lock,
    )

    result = runner.run(
        _request(kind="pixelscan", profile_id=profile_id),
        threading.Event(),
        lambda _value: None,
    )

    assert result.error_code == "timeout"
    assert not lock.released
    assert not runner._semaphore.acquire(timeout=0.01)
    time.sleep(0.2)
    assert browser.sessions[0].is_closed()
    assert lock.released
    assert runner._semaphore.acquire(timeout=0.05)
    runner._semaphore.release()


def test_non_cooperative_target_cannot_ignore_cancellation(
    db_session_factory, settings
):
    entered = threading.Event()

    def ignore_cancel(_session, target_url, **_kwargs):
        entered.set()
        time.sleep(0.2)
        return TargetResult(
            status="passed",
            findings={"page_loaded": True},
            final_url=target_url,
            title="late fixture",
            screenshot=PNG,
        )

    browser = FakeBrowserAdapter()
    runner = _runner(
        db_session_factory,
        _settings(settings),
        browser=browser,
        target=FakeTargetAdapter(ignore_cancel),
    )
    cancel = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        started = time.monotonic()
        future = pool.submit(runner.run, _request(), cancel, lambda _value: None)
        assert entered.wait(1)
        cancel.set()
        result = future.result(timeout=0.15)
        elapsed = time.monotonic() - started

    assert result.status == "cancelled"
    assert elapsed < 0.15
    assert browser.sessions[0].closed
    time.sleep(0.2)
    assert not any(
        thread.name.startswith("diagnostic-adapter-")
        for thread in threading.enumerate()
    )


@pytest.mark.parametrize("hang", ["terminate", "is_closed"])
@pytest.mark.parametrize("trigger", ["deadline", "cancellation"])
def test_hung_interrupt_verification_never_blocks_supervisor_or_releases_lease(
    db_session_factory, settings, hang, trigger
):
    profile_id = _profile(db_session_factory)
    session = HangingCleanupSession(hang)
    target_entered = threading.Event()
    target_release = threading.Event()

    def block_target(_session, target_url, **_kwargs):
        target_entered.set()
        target_release.wait()
        return TargetResult(
            status="passed",
            findings={"page_loaded": True},
            final_url=target_url,
            title="late fixture",
            screenshot=PNG,
        )

    lock = FakeLock()
    runner = _runner(
        db_session_factory,
        _settings(
            settings,
            diagnostic_timeout_seconds=0.05 if trigger == "deadline" else 1,
            max_concurrent_diagnostics=1,
        ),
        browser=FakeBrowserAdapter(session_factory=lambda: session),
        target=FakeTargetAdapter(block_target),
        lock_factory=lambda _profile_id: lock,
    )
    cancel = threading.Event()
    pool = ThreadPoolExecutor(max_workers=1)
    started = time.monotonic()
    future = pool.submit(
        runner.run,
        _request(kind="pixelscan", profile_id=profile_id),
        cancel,
        lambda _value: None,
    )
    try:
        assert target_entered.wait(1)
        if trigger == "cancellation":
            cancel.set()
        assert session.cleanup_entered.wait(0.15)
        result = future.result(timeout=0.15)
        assert time.monotonic() - started < 0.25
        assert result.status == "failed"
        assert result.error_code == "cleanup_failed"
        assert not lock.released
        assert not runner._semaphore.acquire(timeout=0.01)
    finally:
        target_release.set()
        session.cleanup_release.set()
        future.result(timeout=2)
        pool.shutdown(wait=True)


def test_abandoned_preflights_retain_slots_and_profile_locks_until_exit(
    db_session_factory, settings
):
    release = threading.Event()
    entered = threading.Event()
    state_lock = threading.Lock()
    active = 0
    maximum = 0
    calls = 0

    def stuck_preflight(_snapshot):
        nonlocal active, maximum, calls
        with state_lock:
            active += 1
            calls += 1
            maximum = max(maximum, active)
            if active == 2:
                entered.set()
        release.wait()
        with state_lock:
            active -= 1
        return ProxyPreflightResult()

    locks: dict[str, FakeLock] = {}

    def lock_factory(profile_id):
        lock = locks.setdefault(profile_id, FakeLock())
        return lock

    runner = _runner(
        db_session_factory,
        _settings(
            settings,
            diagnostic_timeout_seconds=0.05,
            max_concurrent_diagnostics=2,
        ),
        proxy_preflight=stuck_preflight,
        lock_factory=lock_factory,
    )
    requests = [
        _request(
            kind="pixelscan",
            profile_id=_profile(db_session_factory, name=f"stuck-{index}"),
        )
        for index in range(3)
    ]
    pool = ThreadPoolExecutor(max_workers=3)
    futures = [
        pool.submit(runner.run, request, threading.Event(), lambda _value: None)
        for request in requests
    ]
    try:
        assert entered.wait(1)
        results = [future.result(timeout=0.2) for future in futures]
        assert all(result.error_code == "timeout" for result in results)
        assert calls == 2
        assert maximum == 2
        assert all(not lock.released for lock in locks.values())
        assert not runner._semaphore.acquire(timeout=0.01)
    finally:
        release.set()
        for future in futures:
            future.result(timeout=2)
        pool.shutdown(wait=True)
    cleanup_deadline = time.monotonic() + 1
    while time.monotonic() < cleanup_deadline and any(
        not lock.released for lock in locks.values()
    ):
        time.sleep(0.005)
    assert all(lock.released for lock in locks.values())
    assert runner._semaphore.acquire(timeout=0.05)
    runner._semaphore.release()


def test_direct_control_uses_and_removes_a_manager_owned_no_proxy_profile(
    db_session_factory, settings
):
    browser = FakeBrowserAdapter()
    runner = _runner(db_session_factory, _settings(settings), browser=browser)
    request = _request()

    result = runner.run(request, threading.Event(), lambda _value: None)

    snapshot = browser.launches[0]
    temporary_profile = Path(snapshot["profile_dir"])
    exact_run_root = settings.data_root / "diagnostics" / request.run_id
    assert snapshot["proxy_id"] is None
    assert snapshot["proxy_url"] is None
    assert snapshot["browser_version"] is None
    assert temporary_profile.parent.resolve() == exact_run_root.resolve()
    assert not temporary_profile.exists()
    assert browser.sessions[0].closed
    report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
    assert report["browser"] == {"tier": "team", "version": "136.0.1.2"}
    assert report["profile"]["fingerprint_revision"] == 1
    assert len(report["profile"]["fingerprint_config_hash"]) == 64
    assert snapshot["fingerprint_seed"] not in json.dumps(report)


def test_proxy_preflight_failure_prevents_launch_and_is_safely_mapped(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)
    browser = FakeBrowserAdapter()

    def reject(_snapshot):
        raise RuntimeError("proxy password=super-secret")

    runner = _runner(
        db_session_factory,
        _settings(settings),
        browser=browser,
        proxy_preflight=reject,
    )

    result = runner.run(
        _request(kind="pixelscan", profile_id=profile_id),
        threading.Event(),
        lambda _value: None,
    )

    assert result.status == "failed"
    assert result.error_code == "proxy_preflight_failed"
    assert browser.launches == []
    report = Path(result.report_path).read_text(encoding="utf-8")
    assert "super-secret" not in report


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (TimeoutError("raw timeout details"), "timeout"),
        (DiagnosticBrowserCrashed("secret crash path"), "browser_crashed"),
        (DiagnosticNetworkError("secret network body"), "network_error"),
        (RuntimeError("unexpected secret"), "diagnostic_failed"),
    ],
)
def test_runner_maps_adapter_failures_without_leaking_details(
    db_session_factory, settings, error, expected_code
):
    target = FakeTargetAdapter(action=lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
    runner = _runner(db_session_factory, _settings(settings), target=target)

    result = runner.run(_request(), threading.Event(), lambda _value: None)

    assert result.status == "failed"
    assert result.error_code == expected_code
    report = Path(result.report_path).read_text(encoding="utf-8")
    assert "secret" not in report
    assert "raw timeout details" not in report


@pytest.mark.parametrize(
    ("status", "unsafe_code", "expected_code"),
    [
        ("passed", "browser_crashed", None),
        ("warning", "password=secret", "target_layout_changed"),
        ("failed", "password=secret", "diagnostic_failed"),
        ("failed", "captcha_user_action_required", "diagnostic_failed"),
    ],
)
def test_runner_normalizes_adapter_error_codes_before_persistence(
    db_session_factory, settings, status, unsafe_code, expected_code
):
    target = FakeTargetAdapter(
        action=lambda _session, target_url, **_kwargs: TargetResult(
            status=status,
            findings={"page_loaded": True},
            final_url=target_url,
            title="fixture",
            screenshot=PNG,
            error_code=unsafe_code,
        )
    )
    runner = _runner(db_session_factory, _settings(settings), target=target)

    result = runner.run(_request(), threading.Event(), lambda _value: None)

    assert result.error_code == expected_code
    report = Path(result.report_path).read_text(encoding="utf-8")
    assert "password=secret" not in report


@pytest.mark.parametrize(
    "target_url",
    [
        "http://pixelscan.net/",
        "https://pixelscan.net.evil.example/",
        "https://pixelscan.net/@outside",
        "https://user:password@pixelscan.net/",
    ],
)
def test_runner_rejects_every_non_allowlisted_target_before_launch(
    db_session_factory, settings, target_url
):
    browser = FakeBrowserAdapter()
    runner = _runner(db_session_factory, _settings(settings), browser=browser)

    result = runner.run(
        _request(kind="pixelscan", profile_id="profile-id", target_url=target_url),
        threading.Event(),
        lambda _value: None,
    )

    assert result.status == "failed"
    assert result.error_code == "diagnostic_failed"
    assert browser.launches == []


def test_artifacts_are_atomic_bounded_and_live_below_the_exact_run_root(tmp_path):
    run_id = str(uuid4())
    paths = write_diagnostic_artifacts(
        tmp_path / "data",
        run_id,
        report={"kind": "direct_google_control", "findings": {"page_loaded": True}},
        screenshot=PNG,
    )

    expected_root = (tmp_path / "data" / "diagnostics" / run_id).resolve()
    assert Path(paths.report_path).parent == expected_root
    assert Path(paths.screenshot_path).parent == expected_root
    assert Path(paths.screenshot_path).read_bytes() == PNG
    assert json.loads(Path(paths.report_path).read_text(encoding="utf-8")) == {
        "findings": {"page_loaded": True},
        "kind": "direct_google_control",
    }
    assert not list(expected_root.glob("*.tmp"))


@pytest.mark.parametrize("run_id", ["../escape", "nested/run", ".", ""])
def test_artifact_writer_rejects_non_exact_run_roots(tmp_path, run_id):
    with pytest.raises(ArtifactBoundaryError):
        write_diagnostic_artifacts(
            tmp_path / "data", run_id, report={"safe": True}, screenshot=PNG
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_artifact_writer_rejects_a_run_root_junction_escape(tmp_path):
    diagnostics_root = tmp_path / "data" / "diagnostics"
    diagnostics_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    run_id = str(uuid4())
    run_root = diagnostics_root / run_id
    linked = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(run_root), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if linked.returncode != 0:
        pytest.skip("Windows junction creation is unavailable")
    try:
        with pytest.raises(ArtifactBoundaryError):
            write_diagnostic_artifacts(
                tmp_path / "data", run_id, report={"safe": True}, screenshot=PNG
            )
        assert not (outside / "report.json").exists()
    finally:
        os.rmdir(run_root)


def test_cancellation_closes_browser_removes_temp_profile_and_releases_slot(
    db_session_factory, settings
):
    entered = threading.Event()

    def wait_for_cancel(_session, _target_url, *, cancel_event, **_kwargs):
        entered.set()
        assert cancel_event.wait(2)
        return TargetResult(
            status="passed",
            findings={"page_loaded": True},
            final_url="https://www.google.com/",
            title="cancelled fixture",
            screenshot=PNG,
        )

    browser = FakeBrowserAdapter()
    runner = _runner(
        db_session_factory,
        _settings(settings, max_concurrent_diagnostics=1),
        browser=browser,
        target=FakeTargetAdapter(wait_for_cancel),
    )
    cancel = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runner.run, _request(), cancel, lambda _value: None)
        assert entered.wait(1)
        cancel.set()
        result = future.result(timeout=2)

    assert result.status == "cancelled"
    assert browser.sessions[0].closed
    assert not Path(browser.launches[0]["profile_dir"]).exists()
    runner._semaphore.acquire(timeout=0.1)
    runner._semaphore.release()


def test_close_failure_uses_terminate_and_returns_typed_cleanup_failure(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)
    browser = FakeBrowserAdapter(
        session_factory=lambda: FakeSession(close_error=RuntimeError("raw close"))
    )
    lock = FakeLock()
    runner = _runner(
        db_session_factory,
        _settings(settings),
        browser=browser,
        lock_factory=lambda _profile_id: lock,
    )

    result = runner.run(
        _request(kind="pixelscan", profile_id=profile_id),
        threading.Event(),
        lambda _value: None,
    )

    assert result.status == "failed"
    assert result.error_code == "cleanup_failed"
    assert browser.sessions[0].terminate_calls == 1
    assert browser.sessions[0].is_closed()
    assert lock.released


def test_unverified_browser_cleanup_retains_profile_lock_and_concurrency_slot(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)
    browser = FakeBrowserAdapter(
        session_factory=lambda: FakeSession(
            close_error=RuntimeError("raw close"),
            terminate_error=RuntimeError("raw terminate"),
        )
    )
    lock = FakeLock()
    runner = _runner(
        db_session_factory,
        _settings(settings, max_concurrent_diagnostics=1),
        browser=browser,
        lock_factory=lambda _profile_id: lock,
    )

    result = runner.run(
        _request(kind="pixelscan", profile_id=profile_id),
        threading.Event(),
        lambda _value: None,
    )

    assert result.status == "failed"
    assert result.error_code == "cleanup_failed"
    assert not browser.sessions[0].is_closed()
    assert not lock.released
    assert not runner._semaphore.acquire(timeout=0.01)


def test_late_cleanup_failure_is_observable_and_keeps_ownership_lease(
    db_session_factory, settings
):
    profile_id = _profile(db_session_factory)
    observed = []
    observed_event = threading.Event()

    def observe(result):
        observed.append(result)
        observed_event.set()

    session = FakeSession(
        close_error=RuntimeError("raw close"),
        terminate_error=RuntimeError("raw terminate"),
    )

    def late_target(_session, target_url, **_kwargs):
        time.sleep(0.2)
        return TargetResult(
            status="passed",
            findings={"page_loaded": True},
            final_url=target_url,
            title="late cleanup fixture",
            screenshot=PNG,
        )

    lock = FakeLock()
    runner = _runner(
        db_session_factory,
        _settings(
            settings,
            diagnostic_timeout_seconds=0.05,
            max_concurrent_diagnostics=1,
        ),
        browser=FakeBrowserAdapter(session_factory=lambda: session),
        target=FakeTargetAdapter(late_target),
        lock_factory=lambda _profile_id: lock,
        deferred_result=observe,
    )

    result = runner.run(
        _request(kind="pixelscan", profile_id=profile_id),
        threading.Event(),
        lambda _value: None,
    )

    assert result.status == "failed"
    assert result.error_code == "cleanup_failed"
    assert observed_event.wait(1)
    assert len(observed) == 1
    assert observed[0].status == "failed"
    assert observed[0].error_code == "cleanup_failed"
    assert Path(observed[0].report_path).exists()
    assert not lock.released
    assert not runner._semaphore.acquire(timeout=0.01)


def test_temporary_profile_removal_failure_cannot_return_passed(
    db_session_factory, settings, monkeypatch
):
    real_rmtree = runner_module.shutil.rmtree
    attempted = []

    def fail_profile_removal(path, *args, **kwargs):
        attempted.append(Path(path))
        if Path(path).name.startswith("profile-"):
            raise OSError("raw removal path")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(runner_module.shutil, "rmtree", fail_profile_removal)
    runner = _runner(db_session_factory, _settings(settings))

    result = runner.run(_request(), threading.Event(), lambda _value: None)

    assert result.status == "failed"
    assert result.error_code == "cleanup_failed"
    assert attempted
    assert attempted[0].exists()
    real_rmtree(attempted[0])


@pytest.mark.parametrize(
    ("final_url", "expected"),
    [
        (
            "https://consent.google.com/m?continue=https%3A%2F%2Fwww.google.com#notice",
            "https://consent.google.com/m",
        ),
        (
            "https://www.google.com/sorry/index?continue=secret#captcha",
            "https://www.google.com/sorry/index",
        ),
        ("https://www.google.com/search?q=secret#fragment", "https://www.google.com/search"),
        ("https://evil.example/sorry?secret=1", "https://www.google.com/search"),
        ("http://www.google.com/sorry?secret=1", "https://www.google.com/search"),
        (
            "https://user:password@www.google.com/sorry?secret=1",
            "https://www.google.com/search",
        ),
    ],
)
def test_report_retains_only_sanitized_allowed_https_redirects(
    db_session_factory, settings, final_url, expected
):
    target = FakeTargetAdapter(
        action=lambda _session, _target_url, **_kwargs: TargetResult(
            status="passed",
            findings={"page_loaded": True},
            final_url=final_url,
            title="redirect fixture",
            screenshot=PNG,
        )
    )
    runner = _runner(db_session_factory, _settings(settings), target=target)

    result = runner.run(_request(), threading.Event(), lambda _value: None)

    report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
    assert report["target"]["final_url"] == expected
    assert "secret" not in report["target"]["final_url"]
    assert "password" not in report["target"]["final_url"]


@pytest.mark.parametrize(
    ("kind", "final_url", "expected"),
    [
        (
            "direct_google_control",
            "https://www.google.com/search/sensitive-token-789",
            "https://www.google.com/search",
        ),
        (
            "direct_google_control",
            "https://www.google.com/sorry/sensitive-token-789",
            "https://www.google.com/search",
        ),
        (
            "direct_google_control",
            "https://consent.google.com/sensitive-token-789",
            "https://www.google.com/search",
        ),
        (
            "pixelscan",
            "https://pixelscan.net/account/sensitive-token-789",
            "https://pixelscan.net/",
        ),
        (
            "iphey",
            "https://iphey.com/result/sensitive-token-789",
            "https://iphey.com/",
        ),
        (
            "cloudflare",
            "https://challenge.cloudflare.com/turnstile/v0/generic/sensitive-token-789",
            "https://challenge.cloudflare.com/turnstile/v0/generic/",
        ),
        (
            "google_search",
            "https://www.google.com/search/sensitive-token-789",
            "https://www.google.com/search",
        ),
    ],
)
def test_report_rejects_same_host_paths_outside_narrow_target_policy(
    db_session_factory, settings, kind, final_url, expected
):
    target = FakeTargetAdapter(
        action=lambda _session, _target_url, **_kwargs: TargetResult(
            status="passed",
            findings={},
            final_url=final_url,
            title="path policy fixture",
            screenshot=PNG,
        )
    )
    profile_id = None
    if kind != "direct_google_control":
        profile_id = _profile(db_session_factory, name=f"path-{kind}")
    runner = _runner(db_session_factory, _settings(settings), target=target)

    result = runner.run(
        _request(kind=kind, profile_id=profile_id),
        threading.Event(),
        lambda _value: None,
    )

    report_text = Path(result.report_path).read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert report["target"]["final_url"] == expected
    assert "sensitive-token-789" not in report_text


def test_concurrency_never_exceeds_the_configured_bound(
    db_session_factory, settings
):
    release = threading.Event()
    lock = threading.Lock()
    active = 0
    maximum = 0

    def blocking(_session, target_url, **_kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        release.wait(2)
        with lock:
            active -= 1
        return TargetResult(
            status="passed",
            findings={"page_loaded": True},
            final_url=target_url,
            title="fixture",
            screenshot=PNG,
        )

    runner = _runner(
        db_session_factory,
        _settings(settings, max_concurrent_diagnostics=2),
        target=FakeTargetAdapter(blocking),
    )
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(runner.run, _request(), threading.Event(), lambda _value: None)
            for _ in range(3)
        ]
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and maximum < 2:
            time.sleep(0.01)
        assert maximum == 2
        release.set()
        results = [future.result(timeout=2) for future in futures]

    assert all(result.status == "passed" for result in results)
    assert maximum == 2


@pytest.mark.parametrize(
    ("report", "screenshot", "report_limit", "screenshot_limit"),
    [
        ({"large": "x" * 100}, None, 16, 1024),
        ({"safe": True}, b"x" * 100, 1024, 16),
    ],
)
def test_artifact_writer_rejects_oversized_payloads_without_partial_files(
    tmp_path, report, screenshot, report_limit, screenshot_limit
):
    run_id = str(uuid4())
    with pytest.raises(ArtifactBoundaryError):
        write_diagnostic_artifacts(
            tmp_path / "data",
            run_id,
            report=report,
            screenshot=screenshot,
            max_report_bytes=report_limit,
            max_screenshot_bytes=screenshot_limit,
        )

    run_root = tmp_path / "data" / "diagnostics" / run_id
    assert not (run_root / "report.json").exists()
    assert not (run_root / "screenshot.png").exists()
    assert not list(run_root.glob("*.tmp")) if run_root.exists() else True


def test_atomic_artifact_interruption_removes_temporary_file(
    tmp_path, monkeypatch
):
    run_id = str(uuid4())

    def interrupt_replace(_source, _destination):
        raise OSError("simulated interruption")

    monkeypatch.setattr(artifacts_module.os, "replace", interrupt_replace)
    with pytest.raises(ArtifactBoundaryError):
        write_diagnostic_artifacts(
            tmp_path / "data",
            run_id,
            report={"safe": True},
            screenshot=PNG,
        )

    run_root = tmp_path / "data" / "diagnostics" / run_id
    assert not (run_root / "report.json").exists()
    assert not (run_root / "screenshot.png").exists()
    assert not list(run_root.glob("*.tmp"))
