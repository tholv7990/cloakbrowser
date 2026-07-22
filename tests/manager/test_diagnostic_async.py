from __future__ import annotations

import threading
import time
import sqlite3
from uuid import UUID

from fastapi.testclient import TestClient

from manager_backend.features.diagnostics.runner import (
    BrowserLaunch,
    DiagnosticResult,
    ProxyPreflightResult,
    TargetResult,
)
from manager_backend.main import create_app


class Session:
    def __init__(self) -> None:
        self.closed = threading.Event()

    def close(self) -> None:
        self.closed.set()

    def terminate(self) -> None:
        self.closed.set()

    def is_closed(self) -> bool:
        return self.closed.is_set()


class CloseRaisesSession(Session):
    def close(self) -> None:
        raise RuntimeError("private close failure")


class Browser:
    def __init__(self, session_factory=Session) -> None:
        self.session_factory = session_factory
        self.sessions: list[Session] = []

    def launch(self, _snapshot, **_kwargs) -> BrowserLaunch:
        session = self.session_factory()
        self.sessions.append(session)
        return BrowserLaunch(session=session, tier="free", version="150.0.0.0")


class PassingTarget:
    def run(self, _session, target_url, *, progress, **_kwargs) -> TargetResult:
        progress(55)
        progress(40)
        progress(90)
        return TargetResult(
            status="passed",
            findings={"page_loaded": True, "results_visible": True},
            final_url=target_url,
            title="Diagnostic fixture",
            screenshot=None,
        )


class BlockingTarget:
    def __init__(self) -> None:
        self.started = threading.Event()

    def run(self, _session, target_url, *, cancel_event, **_kwargs) -> TargetResult:
        self.started.set()
        assert cancel_event.wait(3)
        return TargetResult(
            status="passed",
            findings={"page_loaded": True},
            final_url=target_url,
            title="must not complete",
            screenshot=None,
        )


class StubbornTarget:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, _session, target_url, **_kwargs) -> TargetResult:
        self.started.set()
        assert self.release.wait(3)
        return TargetResult(
            status="passed",
            findings={"page_loaded": True},
            final_url=target_url,
            title="late local fixture",
            screenshot=None,
        )


def _app(settings, browser, target):
    return create_app(
        settings,
        diagnostic_browser_adapter=browser,
        diagnostic_target_adapter=target,
        diagnostic_proxy_preflight=lambda _snapshot: ProxyPreflightResult(
            proxy_url=None, classification="direct"
        ),
    )


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/setup",
        headers={"Origin": "http://127.0.0.1:5173"},
        json={"email": "owner@example.com", "password": "long test password"},
    )
    assert response.status_code == 201
    return {
        "Origin": "http://127.0.0.1:5173",
        "X-CSRF-Token": response.json()["csrf_token"],
    }


def _wait_terminal(client: TestClient, headers: dict[str, str], run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/diagnostics/{run_id}", headers=headers).json()
        if body["status"] not in {"queued", "running"}:
            return body
        time.sleep(0.01)
    raise AssertionError("diagnostic did not reach a terminal state")


def test_background_worker_publishes_monotonic_bounded_safe_events(settings):
    browser = Browser()
    with TestClient(_app(settings, browser, PassingTarget())) as client:
        headers = _login(client)
        with client.websocket_connect(
            "/api/v1/events", headers={"Origin": "http://127.0.0.1:5173"}
        ) as socket:
            assert socket.receive_json()["type"] == "runtime.snapshot"
            created = client.post(
                "/api/v1/diagnostics/direct-google-control", headers=headers
            )
            assert created.status_code == 202
            run_id = created.json()["id"]

            diagnostic_events = []
            while not any(
                event["type"] == "diagnostic.completed"
                for event in diagnostic_events
            ):
                event = socket.receive_json()
                if event["type"].startswith("diagnostic."):
                    diagnostic_events.append(event)

        terminal = _wait_terminal(client, headers, run_id)

    assert terminal["status"] == "passed"
    assert terminal["progress"] == 100
    progress = [
        event["diagnostic"]["progress"]
        for event in diagnostic_events
        if event["type"] == "diagnostic.progress"
    ]
    assert progress == sorted(set(progress))
    assert progress[0] >= 0 and progress[-1] <= 100
    assert diagnostic_events[-1]["diagnostic"] == {
        "id": run_id,
        "profile_id": None,
        "kind": "direct_google_control",
        "status": "passed",
        "progress": 100,
        "error_code": None,
    }
    serialized = str(diagnostic_events)
    for forbidden in ("Diagnostic fixture", "target_url", "findings", "cookie", "proxy"):
        assert forbidden not in serialized
    assert browser.sessions and browser.sessions[0].closed.is_set()


def test_cancel_signals_runner_waits_for_cleanup_then_persists_cancelled(settings):
    browser = Browser()
    target = BlockingTarget()
    with TestClient(_app(settings, browser, target)) as client:
        headers = _login(client)
        created = client.post(
            "/api/v1/diagnostics/direct-google-control", headers=headers
        ).json()
        assert target.started.wait(2)

        cancelled = client.post(
            f"/api/v1/diagnostics/{created['id']}/cancel", headers=headers
        )

        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["progress"] == 100
        assert browser.sessions[0].closed.is_set()
        assert client.app.state.diagnostic_executor.task_count == 0


def test_cancel_reports_cleanup_failed_and_retains_ownership_until_stubborn_adapter_exits(
    settings,
):
    settings = settings.model_copy(
        update={
            "max_concurrent_diagnostics": 1,
            "diagnostic_timeout_seconds": 0.1,
            "diagnostic_cleanup_wait_seconds": 0.05,
        }
    )
    target = StubbornTarget()
    browser = Browser()
    app = _app(settings, browser, target)
    with TestClient(app) as client:
        headers = _login(client)
        created = client.post(
            "/api/v1/diagnostics/direct-google-control", headers=headers
        ).json()
        assert target.started.wait(2)

        cancelled = client.post(
            f"/api/v1/diagnostics/{created['id']}/cancel", headers=headers
        )

        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "failed"
        assert cancelled.json()["error_code"] == "cleanup_failed"
        assert app.state.diagnostic_executor.task_count > 0
        assert app.state.diagnostic_runner.cleanup_ownership_count > 0
        run_root = settings.data_root / "diagnostics" / created["id"]
        assert any(path.name.startswith("profile-") for path in run_root.iterdir())

        blocked = client.post(
            "/api/v1/diagnostics/direct-google-control", headers=headers
        ).json()
        blocked = _wait_terminal(client, headers, blocked["id"])
        assert blocked["status"] == "failed"
        assert blocked["error_code"] == "timeout"
        assert len(browser.sessions) == 1

        target.release.set()
        deadline = time.monotonic() + 2
        while (
            app.state.diagnostic_executor.task_count
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert app.state.diagnostic_executor.task_count == 0
        assert app.state.diagnostic_runner.cleanup_ownership_count == 0
        assert not any(path.name.startswith("profile-") for path in run_root.iterdir())


def test_close_error_with_successful_terminate_releases_all_ownership(settings):
    browser = Browser(session_factory=CloseRaisesSession)
    app = _app(settings, browser, PassingTarget())
    with TestClient(app) as client:
        headers = _login(client)
        created = client.post(
            "/api/v1/diagnostics/direct-google-control", headers=headers
        ).json()
        terminal = _wait_terminal(client, headers, created["id"])
        assert terminal["status"] == "failed"
        assert terminal["error_code"] == "cleanup_failed"
        assert browser.sessions[0].closed.is_set()
        assert app.state.diagnostic_runner.cleanup_ownership_count == 0
        assert app.state.diagnostic_executor.task_count == 0


def test_deferred_close_error_releases_lease_after_stubborn_adapter_exits(settings):
    bounded = settings.model_copy(
        update={"diagnostic_cleanup_wait_seconds": 0.05}
    )
    target = StubbornTarget()
    browser = Browser(session_factory=CloseRaisesSession)
    app = _app(bounded, browser, target)
    with TestClient(app) as client:
        headers = _login(client)
        created = client.post(
            "/api/v1/diagnostics/direct-google-control", headers=headers
        ).json()
        assert target.started.wait(2)
        cancelled = client.post(
            f"/api/v1/diagnostics/{created['id']}/cancel", headers=headers
        ).json()
        assert cancelled["status"] == "failed"
        assert cancelled["error_code"] == "cleanup_failed"
        assert app.state.diagnostic_runner.cleanup_ownership_count > 0

        target.release.set()
        deadline = time.monotonic() + 2
        while app.state.diagnostic_executor.task_count and time.monotonic() < deadline:
            time.sleep(0.01)
        assert browser.sessions[0].closed.is_set()
        assert app.state.diagnostic_runner.cleanup_ownership_count == 0
        assert app.state.diagnostic_executor.task_count == 0


def test_profile_lock_remains_owned_until_stubborn_cleanup_exits(settings):
    bounded = settings.model_copy(
        update={"diagnostic_cleanup_wait_seconds": 0.05}
    )
    target = StubbornTarget()
    app = _app(bounded, Browser(), target)
    with TestClient(app) as client:
        headers = _login(client)
        profile_id = client.post(
            "/api/v1/profiles",
            headers=headers,
            json={"name": "cleanup-lock-profile"},
        ).json()["id"]
        created = client.post(
            "/api/v1/diagnostics/pixelscan",
            headers=headers,
            json={"profile_id": profile_id},
        ).json()
        assert target.started.wait(2)
        lock_path = bounded.profile_root / profile_id / ".runtime.lock"
        assert lock_path.exists()

        cancelled = client.post(
            f"/api/v1/diagnostics/{created['id']}/cancel", headers=headers
        ).json()
        assert cancelled["status"] == "failed"
        assert cancelled["error_code"] == "cleanup_failed"
        assert lock_path.exists()
        assert app.state.diagnostic_executor.task_count > 0

        target.release.set()
        deadline = time.monotonic() + 2
        while lock_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not lock_path.exists()
        assert app.state.diagnostic_executor.task_count == 0


def test_lifespan_shutdown_cancels_and_awaits_owned_diagnostics(settings):
    browser = Browser()
    target = BlockingTarget()
    app = _app(settings, browser, target)
    with TestClient(app) as client:
        headers = _login(client)
        created = client.post(
            "/api/v1/diagnostics/direct-google-control", headers=headers
        ).json()
        assert target.started.wait(2)

    assert browser.sessions[0].closed.is_set()
    assert app.state.diagnostic_executor.task_count == 0
    with app.state.session_factory() as session:
        from manager_backend.models import DiagnosticRun

        assert session.get(DiagnosticRun, created["id"]).status == "cancelled"


def test_lifespan_shutdown_waits_for_stubborn_owned_cleanup(settings):
    target = StubbornTarget()
    app = _app(settings, Browser(), target)
    client = TestClient(app)
    client.__enter__()
    headers = _login(client)
    created = client.post(
        "/api/v1/diagnostics/direct-google-control", headers=headers
    ).json()
    assert target.started.wait(2)

    exited = threading.Event()
    errors = []

    def close_client() -> None:
        try:
            client.__exit__(None, None, None)
        except Exception as error:
            errors.append(error)
        finally:
            exited.set()

    closer = threading.Thread(target=close_client)
    closer.start()
    time.sleep(0.05)
    assert not exited.is_set()
    assert app.state.diagnostic_executor.task_count > 0
    target.release.set()
    assert exited.wait(2)
    closer.join(timeout=1)
    assert errors == []
    assert app.state.diagnostic_executor.task_count == 0
    with app.state.session_factory() as session:
        from manager_backend.models import DiagnosticRun

        assert session.get(DiagnosticRun, created["id"]).status == "cancelled"


def test_shutdown_surfaces_cleanup_that_exceeds_its_bounded_wait(settings):
    bounded = settings.model_copy(
        update={"diagnostic_shutdown_cleanup_wait_seconds": 0.1}
    )
    target = StubbornTarget()
    app = _app(bounded, Browser(), target)
    client = TestClient(app)
    client.__enter__()
    try:
        headers = _login(client)
        client.post(
            "/api/v1/diagnostics/direct-google-control", headers=headers
        )
        assert target.started.wait(2)
        started = time.monotonic()
        try:
            client.portal.call(app.state.diagnostic_executor.shutdown)
            raise AssertionError("shutdown hid pending diagnostic cleanup")
        except RuntimeError as error:
            assert "diagnostic" in str(error)
        assert time.monotonic() - started < 0.5
        assert app.state.diagnostic_executor.task_count > 0
        assert app.state.diagnostic_runner.cleanup_ownership_count > 0
        target.release.set()
        deadline = time.monotonic() + 2
        while app.state.diagnostic_executor.task_count and time.monotonic() < deadline:
            time.sleep(0.01)
        client.portal.call(app.state.diagnostic_executor.shutdown)
        assert app.state.diagnostic_executor.task_count == 0
    finally:
        target.release.set()
        client.__exit__(None, None, None)


def test_diagnostic_mutations_remain_authenticated_and_csrf_protected(settings):
    with TestClient(_app(settings, Browser(), PassingTarget())) as client:
        assert (
            client.post("/api/v1/diagnostics/direct-google-control").status_code
            == 403
        )
        headers = _login(client)
        no_csrf = client.post(
            "/api/v1/diagnostics/direct-google-control",
            headers={"Origin": headers["Origin"]},
        )
        assert no_csrf.status_code == 403


class ImmediateCleanupOwnership:
    def __init__(self) -> None:
        self.owned: set[UUID] = set()

    def begin_cleanup_ownership(self, run_id: UUID) -> None:
        self.owned.add(run_id)

    def wait_for_cleanup(self, run_id: UUID, _timeout) -> bool:
        return run_id in self.owned

    def acknowledge_cleanup(self, run_id: UUID) -> bool:
        self.owned.discard(run_id)
        return True

    @property
    def cleanup_ownership_count(self) -> int:
        return len(self.owned)


class DeferredRunner(ImmediateCleanupOwnership):
    def __init__(self) -> None:
        super().__init__()
        self.callback = None
        self.first_run_id: str | None = None

    def set_deferred_result_callback(self, callback) -> None:
        self.callback = callback

    def run(self, request, _cancel_event, progress) -> DiagnosticResult:
        progress(50)
        if self.first_run_id is None:
            self.first_run_id = request.run_id
            self.callback(
                UUID(request.run_id),
                DiagnosticResult(
                    kind=request.kind,
                    status="failed",
                    findings={},
                    error_code="cleanup_failed",
                ),
            )
        return DiagnosticResult(
            kind=request.kind,
            status="passed",
            findings={"page_loaded": True},
        )


def test_deferred_cleanup_amends_only_the_explicit_run_uuid(db_session_factory):
    import asyncio

    from manager_backend.events import EventBroker
    from manager_backend.features.diagnostics.service import (
        DiagnosticExecutor,
        DiagnosticManager,
    )

    async def scenario():
        manager = DiagnosticManager(db_session_factory)
        runner = DeferredRunner()
        executor = DiagnosticExecutor(manager, runner, EventBroker())
        executor.start()
        first = await asyncio.to_thread(
            manager.create, "direct_google_control", None
        )
        second = await asyncio.to_thread(
            manager.create, "direct_google_control", None
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            correlated_id = runner.first_run_id
            if correlated_id is None:
                await asyncio.sleep(0.01)
                continue
            other_id = second.id if correlated_id == first.id else first.id
            first_current = await asyncio.to_thread(manager.current, correlated_id)
            second_current = await asyncio.to_thread(manager.current, other_id)
            if (
                first_current.error_code == "cleanup_failed"
                and second_current.status == "passed"
            ):
                break
            await asyncio.sleep(0.01)
        await executor.shutdown()
        return first_current, second_current, executor.task_count

    first, second, task_count = asyncio.run(scenario())
    assert first.status == "failed"
    assert first.error_code == "cleanup_failed"
    assert second.status == "passed"
    assert second.error_code is None
    assert task_count == 0


def test_scheduler_rejects_new_work_after_executor_shutdown(db_session_factory):
    import asyncio

    from manager_backend.events import EventBroker
    from manager_backend.features.diagnostics.service import (
        DiagnosticExecutor,
        DiagnosticManager,
    )

    async def scenario():
        manager = DiagnosticManager(db_session_factory)
        executor = DiagnosticExecutor(manager, DeferredRunner(), EventBroker())
        executor.start()
        await executor.shutdown()
        return await asyncio.to_thread(
            manager.create, "direct_google_control", None
        )

    created = asyncio.run(scenario())
    assert created.status == "failed"
    assert created.error_code == "scheduler_unavailable"


class RacingRunner(ImmediateCleanupOwnership):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def set_deferred_result_callback(self, _callback) -> None:
        return None

    def run(self, request, cancel_event, _progress) -> DiagnosticResult:
        self.started.set()
        deadline = time.monotonic() + 2
        while not self.release.is_set() and not cancel_event.is_set():
            if time.monotonic() >= deadline:
                raise AssertionError("race runner was not released")
            time.sleep(0.001)
        if cancel_event.is_set():
            return DiagnosticResult(
                kind=request.kind, status="cancelled", findings={}
            )
        return DiagnosticResult(
            kind=request.kind,
            status="passed",
            findings={"page_loaded": True},
        )


def test_cancel_complete_races_leave_exactly_one_terminal_row(db_session_factory):
    import asyncio

    from manager_backend.errors import ManagerError
    from manager_backend.events import EventBroker
    from manager_backend.features.diagnostics.service import (
        DiagnosticExecutor,
        DiagnosticManager,
        TERMINAL_STATUSES,
    )

    async def scenario():
        statuses = []
        for index in range(20):
            manager = DiagnosticManager(db_session_factory)
            runner = RacingRunner()
            executor = DiagnosticExecutor(manager, runner, EventBroker())
            executor.start()
            created = await asyncio.to_thread(
                manager.create, "direct_google_control", None
            )
            assert await asyncio.to_thread(runner.started.wait, 2)
            cancellation = asyncio.create_task(executor.cancel(created.id))
            if index % 2:
                await asyncio.sleep(0)
            runner.release.set()
            try:
                await cancellation
            except ManagerError as error:
                assert error.code == "diagnostic_not_active"
            current = await asyncio.to_thread(manager.current, created.id)
            assert current.status in TERMINAL_STATUSES
            statuses.append(current.status)
            await executor.shutdown()
            assert executor.task_count == 0
        return statuses

    statuses = asyncio.run(scenario())
    assert len(statuses) == 20


def _write_lock(settings):
    connection = sqlite3.connect(
        str(settings.data_root / "manager.db"), timeout=0, isolation_level=None
    )
    connection.execute("BEGIN IMMEDIATE")
    return connection


def _lower_busy_timeout(engine):
    from sqlalchemy import event

    def configure(dbapi_connection, _record, _proxy) -> None:
        dbapi_connection.execute("PRAGMA busy_timeout=20")

    event.listen(engine, "checkout", configure)
    return configure


def test_queued_to_running_retries_real_sqlite_write_contention(settings):
    app = _app(settings, Browser(), PassingTarget())
    with TestClient(app) as client:
        headers = _login(client)
        manager = app.state.diagnostic_manager
        manager.set_scheduler(lambda _run_id: None)
        created = manager.create("direct_google_control", None)
        configure = _lower_busy_timeout(app.state.engine)
        lock = _write_lock(settings)
        try:
            app.state.diagnostic_executor.schedule(created.id)
            time.sleep(0.1)
            assert manager.current(created.id).status == "queued"
            assert app.state.diagnostic_executor.task_count > 0
        finally:
            lock.rollback()
            lock.close()
            from sqlalchemy import event

            event.remove(app.state.engine, "checkout", configure)
        terminal = _wait_terminal(client, headers, created.id)
        assert terminal["status"] == "passed"
        assert app.state.diagnostic_executor.task_count == 0


def test_running_to_terminal_retries_real_sqlite_write_contention(settings):
    target = StubbornTarget()
    app = _app(settings, Browser(), target)
    with TestClient(app) as client:
        headers = _login(client)
        created = client.post(
            "/api/v1/diagnostics/direct-google-control", headers=headers
        ).json()
        assert target.started.wait(2)
        configure = _lower_busy_timeout(app.state.engine)
        lock = _write_lock(settings)
        try:
            target.release.set()
            time.sleep(0.1)
            assert app.state.diagnostic_manager.current(created["id"]).status == "running"
            assert app.state.diagnostic_executor.task_count > 0
        finally:
            lock.rollback()
            lock.close()
            from sqlalchemy import event

            event.remove(app.state.engine, "checkout", configure)
        terminal = _wait_terminal(client, headers, created["id"])
        assert terminal["status"] == "passed"
        assert app.state.diagnostic_executor.task_count == 0
