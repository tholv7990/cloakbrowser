from __future__ import annotations

import json
from fastapi.testclient import TestClient

from manager_backend.features.runtime.reconcile import cleanup_stale_locks, reconcile_runtimes
from manager_backend.features.runtime.service import create_runtime_session, transition_runtime
from manager_backend.models import Profile, RuntimeSession
from manager_backend.main import create_app


def _running_runtime(session_factory, name="reconcile"):
    with session_factory() as session:
        profile = Profile(
            name=name,
            fingerprint_seed="735711",
            fingerprint_config_hash="a" * 64,
        )
        session.add(profile)
        session.commit()
        runtime = create_runtime_session(session, profile)
        transition_runtime(session, runtime, "starting")
        transition_runtime(session, runtime, "running")
        return runtime.id


class Inspector:
    def __init__(self, result):
        self.result = result

    def inspect(self, _runtime, _profile_dir):
        return self.result


def test_restart_marks_runtime_crashed_when_owned_process_is_not_verified(
    db_session_factory, settings
):
    runtime_id = _running_runtime(db_session_factory)
    summary = reconcile_runtimes(
        db_session_factory, settings, inspector=Inspector("missing")
    )
    with db_session_factory() as session:
        runtime = session.get(RuntimeSession, runtime_id)
        assert runtime.state == "crashed"
        assert runtime.last_message == "manager_restarted"
    assert summary == {"crashed": 1, "detached": 0, "reconnected": 0}


def test_restart_detaches_live_process_that_cannot_be_safely_controlled(
    db_session_factory, settings
):
    runtime_id = _running_runtime(db_session_factory, "unsafe")
    summary = reconcile_runtimes(
        db_session_factory, settings, inspector=Inspector("unsafe")
    )
    with db_session_factory() as session:
        runtime = session.get(RuntimeSession, runtime_id)
        assert runtime.state == "detached"
        assert runtime.last_message == "browser_detached"
    assert summary["detached"] == 1


def test_restart_keeps_verified_reconnected_runtime_running(db_session_factory, settings):
    runtime_id = _running_runtime(db_session_factory, "reconnected")
    summary = reconcile_runtimes(
        db_session_factory,
        settings,
        inspector=Inspector("owned"),
        reconnect=lambda _runtime: True,
    )
    with db_session_factory() as session:
        runtime = session.get(RuntimeSession, runtime_id)
        assert runtime.state == "running"
        assert runtime.last_message == "browser_reconnected"
    assert summary["reconnected"] == 1


def test_stale_lock_is_removed_only_after_owner_is_verified_dead(settings):
    profile_dir = settings.profile_root / "profile-one"
    profile_dir.mkdir(parents=True)
    lock_path = profile_dir / ".runtime.lock"
    lock_path.write_text(
        json.dumps(
            {
                "profile_id": "profile-one",
                "manager_pid": 1234,
                "manager_created_at": 5678.0,
            }
        ),
        encoding="utf-8",
    )
    assert cleanup_stale_locks(settings, owner_is_live=lambda _metadata: True) == 0
    assert lock_path.exists()
    assert cleanup_stale_locks(settings, owner_is_live=lambda _metadata: False) == 1
    assert not lock_path.exists()


def test_malformed_lock_is_left_in_place(settings):
    profile_dir = settings.profile_root / "profile-malformed"
    profile_dir.mkdir(parents=True)
    lock_path = profile_dir / ".runtime.lock"
    lock_path.write_text("not trusted metadata", encoding="utf-8")
    assert cleanup_stale_locks(settings, owner_is_live=lambda _metadata: False) == 0
    assert lock_path.exists()


def test_app_startup_runs_runtime_reconciliation(db_session_factory, settings):
    runtime_id = _running_runtime(db_session_factory, "startup")
    with TestClient(create_app(settings)) as client:
        assert client.app.state.runtime_reconciliation["crashed"] == 1
        with client.app.state.session_factory() as session:
            assert session.get(RuntimeSession, runtime_id).state == "crashed"


def test_bootstrap_observes_reconciled_stale_runtimes(db_session_factory, settings):
    _running_runtime(db_session_factory, "startup-bootstrap")
    with TestClient(create_app(settings)) as client:
        setup = client.post(
            "/api/v1/auth/setup",
            headers={"Origin": settings.allowed_origin},
            json={
                "email": "owner@example.com",
                "password": "correct horse battery staple",
            },
        )
        assert setup.status_code == 201

        bootstrap = client.get(
            "/api/v1/app/bootstrap", headers={"Origin": settings.allowed_origin}
        )

    assert bootstrap.status_code == 200
    assert bootstrap.json()["running_session_count"] == 0
