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
    def __init__(self, *, tier: str = "team", version: str = "136.0.1.2"):
        self.tier = tier
        self.version = version
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeBrowserAdapter:
    def __init__(self, *, error: Exception | None = None):
        self.error = error
        self.launches: list[dict] = []
        self.sessions: list[FakeSession] = []

    def launch(self, snapshot, *, timeout_seconds, cancel_event):
        self.launches.append(dict(snapshot))
        if self.error is not None:
            raise self.error
        session = FakeSession()
        self.sessions.append(session)
        return BrowserLaunch(session=session, tier=session.tier, version=session.version)


class FakeTargetAdapter:
    def __init__(self, action=None):
        self.action = action or self._success
        self.calls: list[tuple[FakeSession, str, float]] = []

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
    }
    return DiagnosticRequest(
        run_id=str(uuid4()),
        kind=kind,
        profile_id=profile_id,
        target_url=target_url or targets[kind],
    )


def _profile(session_factory, *, name="diagnostic", proxy_id=None) -> str:
    with session_factory() as session:
        profile = Profile(
            name=name,
            fingerprint_seed="4242424242",
            fingerprint_preset="consistent",
            fingerprint_revision=7,
            fingerprint_config_hash="a" * 64,
            browser_version_mode="pinned",
            browser_version="135.0.0.1",
            user_agent_mode="custom",
            custom_user_agent="FixtureAgent/1.0",
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
):
    return DiagnosticRunner(
        session_factory,
        settings,
        browser_adapter=browser or FakeBrowserAdapter(),
        target_adapter=target or FakeTargetAdapter(),
        proxy_preflight=proxy_preflight
        or (lambda _snapshot: ProxyPreflightResult()),
        lock_factory=lock_factory or (lambda _profile_id: FakeLock()),
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
