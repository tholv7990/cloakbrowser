from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Event, get_ident

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError


KINDS = {
    "direct_google_control": "/api/v1/diagnostics/direct-google-control",
    "pixelscan": "/api/v1/diagnostics/pixelscan",
    "iphey": "/api/v1/diagnostics/iphey",
    "cloudflare": "/api/v1/diagnostics/cloudflare",
    "google_search": "/api/v1/diagnostics/google-search",
}
STATUSES = ("queued", "running", "passed", "warning", "failed", "cancelled")


def _profile(client, auth_headers, name="Diagnostic profile"):
    response = client.post(
        "/api/v1/profiles", headers=auth_headers, json={"name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create(client, auth_headers, kind, profile_id=None):
    kwargs = {"headers": auth_headers}
    if profile_id is not None:
        kwargs["json"] = {"profile_id": profile_id}
    return client.post(KINDS[kind], **kwargs)


def test_every_diagnostic_kind_is_created_queued_with_http_202(client, auth_headers):
    scheduled = []
    client.app.state.diagnostic_manager.set_scheduler(scheduled.append)

    for index, kind in enumerate(KINDS):
        profile_id = None
        if kind != "direct_google_control":
            profile_id = _profile(client, auth_headers, f"Diagnostic profile {index}")
        response = _create(client, auth_headers, kind, profile_id)

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["kind"] == kind
        assert body["profile_id"] == profile_id
        assert body["status"] == "queued"
        assert body["progress"] == 0
        assert body["target_url"].startswith("https://")
        assert body["summary"] is None
        assert body["findings"] == {}
        assert body["error_code"] is None
        assert body["error_message"] is None
        assert body["screenshot_path"] is None
        assert body["report_path"] is None

    assert scheduled == [
        item["id"]
        for item in client.get("/api/v1/diagnostics", headers=auth_headers).json()[
            "items"
        ][::-1]
    ]


def test_profile_request_schema_is_strict_and_profile_must_exist(client, auth_headers):
    extra = client.post(
        "/api/v1/diagnostics/pixelscan",
        headers=auth_headers,
        json={"profile_id": "missing", "target_url": "https://evil.invalid"},
    )
    assert extra.status_code == 422
    assert extra.json()["error"]["code"] == "validation_error"

    missing = client.post(
        "/api/v1/diagnostics/pixelscan",
        headers=auth_headers,
        json={"profile_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "profile_not_found"


def test_list_supports_status_kind_profile_and_pagination_filters(client, auth_headers):
    from manager_backend.models import DiagnosticRun, Profile

    with client.app.state.session_factory() as session:
        profiles = [
            Profile(
                name=f"Filter profile {index}",
                fingerprint_seed=str(80_000 + index),
                fingerprint_config_hash=str(index) * 64,
            )
            for index in range(len(STATUSES))
        ]
        session.add_all(profiles)
        session.flush()
        for index, status in enumerate(STATUSES):
            now = datetime(2026, 7, 22, 1, index, tzinfo=timezone.utc)
            session.add(
                DiagnosticRun(
                    profile_id=profiles[index].id,
                    kind="pixelscan" if index % 2 == 0 else "iphey",
                    status=status,
                    target_url=(
                        "https://pixelscan.net/"
                        if index % 2 == 0
                        else "https://iphey.com/"
                    ),
                    progress=min(index * 20, 100),
                    requested_at=now,
                    started_at=now if status != "queued" else None,
                    completed_at=now if status not in {"queued", "running"} else None,
                )
            )
        session.commit()
        expected_profile_id = profiles[2].id

    page = client.get(
        "/api/v1/diagnostics?kind=pixelscan&page=2&page_size=2",
        headers=auth_headers,
    )
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 3
    assert page.json()["page"] == 2
    assert page.json()["page_size"] == 2
    assert page.json()["pages"] == 2
    assert len(page.json()["items"]) == 1

    profile = client.get(
        f"/api/v1/diagnostics?profile={expected_profile_id}", headers=auth_headers
    )
    assert profile.status_code == 200
    assert profile.json()["total"] == 1
    assert profile.json()["items"][0]["profile_id"] == expected_profile_id

    for status in STATUSES:
        filtered = client.get(
            f"/api/v1/diagnostics?status={status}", headers=auth_headers
        )
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["status"] == status


def test_get_and_list_not_found_errors_are_safe(client, auth_headers):
    missing = client.get(
        "/api/v1/diagnostics/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "diagnostic_not_found"
    assert "sql" not in str(missing.json()).lower()

    invalid_filter = client.get(
        "/api/v1/diagnostics?status=complete", headers=auth_headers
    )
    assert invalid_filter.status_code == 422
    assert invalid_filter.json()["error"]["code"] == "validation_error"


def test_only_one_active_run_is_allowed_per_profile(client, auth_headers):
    profile_id = _profile(client, auth_headers)
    first = _create(client, auth_headers, "pixelscan", profile_id)
    assert first.status_code == 202

    conflict = _create(client, auth_headers, "iphey", profile_id)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "diagnostic_already_active"

    assert _create(client, auth_headers, "direct_google_control").status_code == 202
    assert _create(client, auth_headers, "direct_google_control").status_code == 202


def test_cancel_marks_active_run_cancelled_and_rejects_terminal_run(
    client, auth_headers
):
    profile_id = _profile(client, auth_headers)
    created = _create(client, auth_headers, "cloudflare", profile_id).json()

    cancelled = client.post(
        f"/api/v1/diagnostics/{created['id']}/cancel", headers=auth_headers
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["completed_at"] is not None

    repeated = client.post(
        f"/api/v1/diagnostics/{created['id']}/cancel", headers=auth_headers
    )
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "diagnostic_not_active"

    assert _create(client, auth_headers, "google_search", profile_id).status_code == 202


def test_manager_bounds_progress_and_enforces_state_transitions(db_session_factory):
    from manager_backend.errors import ManagerError
    from manager_backend.features.diagnostics.service import DiagnosticManager
    from manager_backend.models import Profile

    with db_session_factory() as session:
        profile = Profile(
            name="Transitions",
            fingerprint_seed="91001",
            fingerprint_config_hash="f" * 64,
        )
        session.add(profile)
        session.commit()
        profile_id = profile.id

    manager = DiagnosticManager(db_session_factory)
    run = manager.create("pixelscan", profile_id)
    running = manager.transition(run.id, "running")
    assert running.started_at is not None
    assert manager.update_progress(run.id, -10).progress == 0
    assert manager.update_progress(run.id, 175).progress == 100
    passed = manager.transition(run.id, "passed")
    assert passed.status == "passed"
    assert passed.progress == 100
    assert passed.completed_at is not None

    with pytest.raises(ManagerError) as caught:
        manager.transition(run.id, "running")
    assert caught.value.code == "invalid_diagnostic_transition"

    with pytest.raises(ManagerError) as caught:
        manager.update_progress(run.id, 50)
    assert caught.value.code == "diagnostic_not_active"


def test_startup_recovery_marks_queued_and_running_orphans_failed(
    db_session_factory,
):
    from manager_backend.features.diagnostics.service import DiagnosticManager
    from manager_backend.models import DiagnosticRun

    with db_session_factory() as session:
        for status in ("queued", "running", "passed"):
            session.add(
                DiagnosticRun(
                    kind="direct_google_control",
                    status=status,
                    target_url="https://www.google.com/search?q=CloakBrowser+diagnostic",
                    progress=10,
                )
            )
        session.commit()

    manager = DiagnosticManager(db_session_factory)
    assert manager.recover_orphans() == 2
    with db_session_factory() as session:
        recovered = list(
            session.query(DiagnosticRun).order_by(DiagnosticRun.requested_at)
        )
        for run in recovered[:2]:
            assert run.status == "failed"
            assert run.progress == 100
            assert run.error_code == "manager_restarted"
            assert run.error_message == "The manager restarted before the diagnostic completed."
            assert run.completed_at is not None
        assert recovered[2].status == "passed"


def test_startup_lifespan_recovers_orphans(settings):
    from fastapi.testclient import TestClient

    from manager_backend.db import create_engine_for, create_session_factory
    from manager_backend.main import create_app
    from manager_backend.models import Base, DiagnosticRun

    engine = create_engine_for(settings)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        run = DiagnosticRun(
            kind="direct_google_control",
            status="queued",
            target_url="https://www.google.com/search?q=CloakBrowser+diagnostic",
        )
        session.add(run)
        session.commit()
        run_id = run.id
    engine.dispose()

    with TestClient(create_app(settings)) as startup_client:
        assert startup_client.app.state.diagnostic_recovered == 1
        with startup_client.app.state.session_factory() as session:
            assert session.get(DiagnosticRun, run_id).status == "failed"


def test_artifact_paths_outside_owned_run_root_and_secrets_are_not_exposed(
    client, auth_headers
):
    from manager_backend.models import DiagnosticRun

    secret = "alice:very-secret-password"
    with client.app.state.session_factory() as session:
        run = DiagnosticRun(
            kind="direct_google_control",
            status="failed",
            target_url="https://www.google.com/search?q=CloakBrowser+diagnostic",
            progress=100,
            summary="Diagnostic failed.",
            findings={},
            screenshot_path=f"C:/outside/{secret}.png",
            report_path=f"C:/outside/{secret}.json",
            error_code="browser_crashed",
            error_message="The browser closed before the diagnostic completed.",
            completed_at=datetime.now(timezone.utc),
        )
        session.add(run)
        session.commit()
        run_id = run.id

    response = client.get(f"/api/v1/diagnostics/{run_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["screenshot_path"] is None
    assert response.json()["report_path"] is None
    assert secret not in response.text


def test_diagnostic_routes_require_authentication_origin_and_csrf(client, auth_headers):
    missing_origin = client.post("/api/v1/diagnostics/direct-google-control")
    assert missing_origin.status_code == 403
    assert missing_origin.json()["error"]["code"] == "invalid_origin"

    foreign_origin = client.post(
        "/api/v1/diagnostics/direct-google-control",
        headers={"Origin": "http://evil.invalid"},
    )
    assert foreign_origin.status_code == 403
    assert foreign_origin.json()["error"]["code"] == "invalid_origin"

    missing_csrf = client.post(
        "/api/v1/diagnostics/direct-google-control",
        headers={"Origin": auth_headers["Origin"]},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "csrf_invalid"

    client.cookies.clear()
    assert client.get("/api/v1/diagnostics").status_code == 401

    unauthenticated_mutation = client.post(
        "/api/v1/diagnostics/direct-google-control",
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert unauthenticated_mutation.status_code == 401


def test_diagnostic_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    data_root = tmp_path / "diagnostic-migration"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(data_root))
    config = Config("manager_backend/alembic.ini")
    command.upgrade(config, "head")

    database = data_root / "manager.db"
    with sqlite3.connect(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(diagnostic_runs)")
        }
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(diagnostic_runs)")
        }
        foreign_keys = list(connection.execute("PRAGMA foreign_key_list(diagnostic_runs)"))

    assert {
        "id",
        "profile_id",
        "kind",
        "status",
        "target_url",
        "requested_at",
        "started_at",
        "completed_at",
        "progress",
        "summary",
        "findings_json",
        "screenshot_path",
        "report_path",
        "error_code",
        "error_message",
    } <= columns
    assert "uq_diagnostic_runs_active_profile" in indexes
    assert any(
        row[2] == "profiles" and row[3] == "profile_id" and row[6] == "SET NULL"
        for row in foreign_keys
    )
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO diagnostic_runs "
                "(id, kind, status, target_url, requested_at, progress, findings_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "bad-target",
                    "pixelscan",
                    "queued",
                    "https://evil.invalid/",
                    "2026-07-22T00:00:00Z",
                    0,
                    "{}",
                ),
            )

    command.downgrade(config, "0009_extensions")
    with sqlite3.connect(database) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='diagnostic_runs'"
        ).fetchone()
    assert table is None


def _manager_profile(db_session_factory, suffix="race"):
    from manager_backend.models import Profile

    with db_session_factory() as session:
        profile = Profile(
            name=f"Diagnostic {suffix}",
            fingerprint_seed=str(abs(hash(suffix)) % 9_000_000_000 + 1_000_000_000),
            fingerprint_config_hash="a" * 64,
        )
        session.add(profile)
        session.commit()
        return profile.id


@pytest.mark.parametrize("attempt", range(20))
def test_cancel_and_pass_race_has_exactly_one_terminal_winner(
    db_session_factory, monkeypatch, attempt
):
    from manager_backend.errors import ManagerError
    from manager_backend.features.diagnostics import service
    from manager_backend.features.diagnostics.service import DiagnosticManager
    from manager_backend.models import DiagnosticRun

    manager = DiagnosticManager(db_session_factory)
    profile_id = _manager_profile(db_session_factory, f"terminal-{attempt}")
    run = manager.create("pixelscan", profile_id)
    manager.transition(run.id, "running")

    original_get = service.get_diagnostic
    loaded = Barrier(2)

    def gated_get(session, diagnostic_id):
        current = original_get(session, diagnostic_id)
        loaded.wait(timeout=5)
        return current

    monkeypatch.setattr(service, "get_diagnostic", gated_get)

    def invoke(operation):
        try:
            return operation()
        except ManagerError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                invoke,
                (
                    lambda: manager.cancel(run.id),
                    lambda: manager.transition(run.id, "passed"),
                ),
            )
        )

    winners = [result for result in results if isinstance(result, DiagnosticRun)]
    losers = [result for result in results if isinstance(result, ManagerError)]
    assert len(winners) == len(losers) == 1
    assert losers[0].code == "diagnostic_not_active"
    with db_session_factory() as session:
        stored = session.get(DiagnosticRun, run.id)
        assert stored.status == winners[0].status
        assert stored.status in {"passed", "cancelled"}


def test_progress_cannot_overwrite_a_concurrent_terminal_result(db_session_factory):
    from manager_backend.errors import ManagerError
    from manager_backend.features.diagnostics.service import DiagnosticManager
    from manager_backend.models import DiagnosticRun

    manager = DiagnosticManager(db_session_factory)
    profile_id = _manager_profile(db_session_factory, "progress-terminal")
    run = manager.create("pixelscan", profile_id)
    manager.transition(run.id, "running")

    engine = db_session_factory.kw["bind"]
    progress_blocked = Event()
    release_progress = Event()
    main_thread = get_ident()

    def pause_progress(_conn, _cursor, statement, _parameters, _context, _many):
        normalized = " ".join(statement.lower().split())
        if (
            get_ident() != main_thread
            and normalized.startswith("update diagnostic_runs set progress=")
        ):
            progress_blocked.set()
            assert release_progress.wait(timeout=5)

    event.listen(engine, "before_cursor_execute", pause_progress)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(manager.update_progress, run.id, 37)
            assert progress_blocked.wait(timeout=5)
            terminal = manager.transition(run.id, "passed")
            release_progress.set()
            try:
                progress_result = pending.result(timeout=5)
            except ManagerError as error:
                progress_result = error
    finally:
        release_progress.set()
        if event.contains(engine, "before_cursor_execute", pause_progress):
            event.remove(engine, "before_cursor_execute", pause_progress)

    assert terminal.status == "passed"
    assert isinstance(progress_result, ManagerError)
    assert progress_result.code == "diagnostic_not_active"
    with db_session_factory() as session:
        stored = session.get(DiagnosticRun, run.id)
        assert stored.status == "passed"
        assert stored.progress == 100


def test_concurrent_progress_updates_compare_the_expected_progress_version(
    db_session_factory, monkeypatch
):
    from manager_backend.errors import ManagerError
    from manager_backend.features.diagnostics import service
    from manager_backend.features.diagnostics.service import DiagnosticManager
    from manager_backend.models import DiagnosticRun

    manager = DiagnosticManager(db_session_factory)
    profile_id = _manager_profile(db_session_factory, "progress-version")
    run = manager.create("pixelscan", profile_id)
    manager.transition(run.id, "running")
    original_get = service.get_diagnostic
    loaded = Barrier(2)

    def gated_get(session, diagnostic_id):
        current = original_get(session, diagnostic_id)
        loaded.wait(timeout=5)
        return current

    monkeypatch.setattr(service, "get_diagnostic", gated_get)

    def update(value):
        try:
            return manager.update_progress(run.id, value)
        except ManagerError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(update, (31, 47)))

    winners = [result for result in results if isinstance(result, DiagnosticRun)]
    losers = [result for result in results if isinstance(result, ManagerError)]
    assert len(winners) == len(losers) == 1
    assert losers[0].code == "diagnostic_conflict"
    with db_session_factory() as session:
        assert session.get(DiagnosticRun, run.id).progress == winners[0].progress


def test_concurrent_create_is_serialized_and_terminal_rows_release_partial_index(
    db_session_factory,
):
    from manager_backend.errors import ManagerError
    from manager_backend.features.diagnostics.service import DiagnosticManager
    from manager_backend.models import DiagnosticRun

    manager = DiagnosticManager(db_session_factory)
    profile_id = _manager_profile(db_session_factory, "create-race")
    start = Barrier(2)

    def create(kind):
        start.wait(timeout=5)
        try:
            return manager.create(kind, profile_id)
        except ManagerError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(create, "pixelscan")
        second = executor.submit(create, "iphey")
        results = [first.result(timeout=10), second.result(timeout=10)]

    winners = [result for result in results if isinstance(result, DiagnosticRun)]
    losers = [result for result in results if isinstance(result, ManagerError)]
    assert len(winners) == len(losers) == 1
    assert losers[0].code == "diagnostic_already_active"

    manager.transition(winners[0].id, "failed")
    retry = manager.create("cloudflare", profile_id)
    assert retry.status == "queued"


@pytest.mark.parametrize("deletion", ["soft", "hard"])
def test_profile_delete_wins_before_create_reservation_without_queued_orphan(
    db_session_factory, deletion
):
    from manager_backend.errors import ManagerError
    from manager_backend.features.diagnostics.service import DiagnosticManager
    from manager_backend.models import DiagnosticRun, Profile

    manager = DiagnosticManager(db_session_factory)
    profile_id = _manager_profile(db_session_factory, f"{deletion}-delete-race")
    engine = db_session_factory.kw["bind"]
    create_attempted = Event()
    main_thread = get_ident()

    def observe_create(_conn, _cursor, statement, _parameters, _context, _many):
        normalized = " ".join(statement.lower().split())
        if get_ident() != main_thread and (
            normalized == "begin immediate"
            or normalized.startswith("insert into diagnostic_runs")
        ):
            create_attempted.set()

    event.listen(engine, "before_cursor_execute", observe_create)
    try:
        with db_session_factory() as deletion_session:
            deletion_session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            profile = deletion_session.get(Profile, profile_id)
            if deletion == "soft":
                profile.deleted_at = datetime.now(timezone.utc)
            else:
                deletion_session.delete(profile)
            deletion_session.flush()
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(manager.create, "pixelscan", profile_id)
                assert create_attempted.wait(timeout=5)
                deletion_session.commit()
                try:
                    result = pending.result(timeout=10)
                except ManagerError as error:
                    result = error
    finally:
        if event.contains(engine, "before_cursor_execute", observe_create):
            event.remove(engine, "before_cursor_execute", observe_create)

    assert isinstance(result, ManagerError)
    assert result.code == "profile_not_found"
    with db_session_factory() as session:
        assert session.scalar(
            session.query(DiagnosticRun.id)
            .filter(DiagnosticRun.profile_id == profile_id)
            .statement
        ) is None


def test_scheduler_failure_is_safe_terminal_and_releases_profile_slot(
    db_session_factory,
):
    from manager_backend.features.diagnostics.service import DiagnosticManager

    profile_id = _manager_profile(db_session_factory, "scheduler-failure")
    secret = "alice:very-secret-password@proxy.invalid"

    def unavailable(_run_id):
        raise RuntimeError(secret)

    manager = DiagnosticManager(db_session_factory, scheduler=unavailable)
    failed = manager.create("pixelscan", profile_id)
    assert failed.status == "failed"
    assert failed.error_code == "scheduler_unavailable"
    assert failed.error_message == "The diagnostic could not be scheduled."
    assert secret not in str(failed.__dict__)

    manager.set_scheduler(lambda _run_id: None)
    retry = manager.create("iphey", profile_id)
    assert retry.status == "queued"


def test_cancellation_during_scheduler_failure_is_not_overwritten(db_session_factory):
    from manager_backend.features.diagnostics.service import DiagnosticManager

    profile_id = _manager_profile(db_session_factory, "scheduler-cancel")
    manager = DiagnosticManager(db_session_factory)

    def cancel_then_fail(run_id):
        manager.cancel(run_id)
        raise RuntimeError("private scheduler detail")

    manager.set_scheduler(cancel_then_fail)
    run = manager.create("pixelscan", profile_id)
    assert run.status == "cancelled"
    assert run.error_code is None
    assert run.error_message is None


def test_create_integrity_classifies_unique_and_foreign_key_constraints_safely(
    db_session_factory,
):
    from manager_backend.errors import ManagerError
    from manager_backend.features.diagnostics.service import DiagnosticManager

    manager = DiagnosticManager(db_session_factory)
    profile_id = _manager_profile(db_session_factory, "integrity-map")
    manager.create("pixelscan", profile_id)

    class ConstraintDetail(Exception):
        def __init__(self, code):
            self.sqlite_errorcode = code

    with db_session_factory() as session:
        with pytest.raises(ManagerError) as unique:
            manager._map_create_integrity(  # noqa: SLF001 - constraint boundary regression
                session,
                IntegrityError(
                    "private insert detail",
                    {},
                    ConstraintDetail(sqlite3.SQLITE_CONSTRAINT_UNIQUE),
                ),
                profile_id,
            )
    assert unique.value.code == "diagnostic_already_active"
    assert "private" not in unique.value.message

    missing_id = "00000000-0000-0000-0000-000000000000"
    with db_session_factory() as session:
        with pytest.raises(ManagerError) as foreign_key:
            manager._map_create_integrity(  # noqa: SLF001 - constraint boundary regression
                session,
                IntegrityError(
                    "private foreign key detail",
                    {},
                    ConstraintDetail(sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY),
                ),
                missing_id,
            )
    assert foreign_key.value.code == "profile_not_found"
    assert "private" not in foreign_key.value.message


def test_typed_result_update_rejects_unknown_keys_nested_and_arbitrary_strings():
    from manager_backend.features.diagnostics.schemas import DiagnosticResultUpdate

    invalid_findings = (
        {"cookie": True},
        {"consistency": {"password": "secret"}},
        {"consistency": "C:/Users/Admin/private.txt"},
    )
    for findings in invalid_findings:
        with pytest.raises(ValidationError):
            DiagnosticResultUpdate(
                kind="pixelscan",
                status="warning",
                findings=findings,
                error_code="target_layout_changed",
            )


def test_typed_result_persistence_and_legacy_serialization_are_bounded(
    client, auth_headers
):
    from manager_backend.features.diagnostics.schemas import DiagnosticResultUpdate
    from manager_backend.models import DiagnosticRun

    client.app.state.diagnostic_manager.set_scheduler(lambda _run_id: None)
    profile_id = _profile(client, auth_headers, "Bounded result profile")
    created = _create(client, auth_headers, "pixelscan", profile_id).json()
    client.app.state.diagnostic_manager.transition(created["id"], "running")
    owned_root = (
        client.app.state.settings.data_root / "diagnostics" / created["id"]
    )
    screenshot = owned_root / "pixelscan.png"
    completed = client.app.state.diagnostic_manager.store_result(
        created["id"],
        DiagnosticResultUpdate(
            kind="pixelscan",
            status="warning",
            findings={"consistency": "aligned", "automation": "detected"},
            error_code="target_layout_changed",
            screenshot_path=str(screenshot),
        ),
    )
    assert completed.status == "warning"

    secret = "alice:very-secret-password"
    with client.app.state.session_factory() as session:
        legacy = DiagnosticRun(
            kind="google_search",
            status="failed",
            target_url="https://www.google.com/search?q=CloakBrowser+browser+diagnostic",
            progress=100,
            summary=secret,
            findings={
                "page_loaded": True,
                "cookie": secret,
                "results_visible": {"path": f"C:/private/{secret}"},
            },
            screenshot_path=str(
                client.app.state.settings.data_root
                / "diagnostics"
                / "placeholder"
                / "outside.png"
            ),
            report_path=f"C:/outside/{secret}.json",
            error_code="private_exception",
            error_message=secret,
            completed_at=datetime.now(timezone.utc),
        )
        session.add(legacy)
        session.flush()
        contained = (
            client.app.state.settings.data_root
            / "diagnostics"
            / legacy.id
            / "report.json"
        )
        legacy.screenshot_path = str(contained)
        session.commit()
        legacy_id = legacy.id

    safe = client.get(
        f"/api/v1/diagnostics/{legacy_id}", headers=auth_headers
    ).json()
    assert safe["target_url"] == (
        "https://www.google.com/search?q=CloakBrowser+browser+diagnostic"
    )
    assert safe["summary"] == "Diagnostic failed."
    assert safe["findings"] == {"page_loaded": True}
    assert safe["error_code"] == "diagnostic_failed"
    assert safe["error_message"] == "The diagnostic could not be completed."
    assert safe["screenshot_path"] == str(contained.resolve())
    assert safe["report_path"] is None
    assert secret not in str(safe)

    bounded = client.get(
        f"/api/v1/diagnostics/{created['id']}", headers=auth_headers
    ).json()
    assert bounded["findings"] == {
        "consistency": "aligned",
        "automation": "detected",
    }
    assert bounded["summary"] == "Diagnostic completed with warnings."
    assert bounded["error_code"] == "target_layout_changed"
    assert bounded["screenshot_path"] == str(screenshot.resolve())
