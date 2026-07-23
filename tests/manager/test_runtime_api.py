from __future__ import annotations

from datetime import datetime, timezone
import threading
import time

from manager_backend.features.runtime.manager import RuntimeManager
from manager_backend.features.runtime.reconcile import reconcile_runtimes
from manager_backend.features.runtime.service import create_runtime_session, transition_runtime
from manager_backend.models import Profile, ProfileLogEntry, RuntimeSession


class Handle:
    def __init__(self):
        self.closed = threading.Event()

    def close(self):
        self.closed.set()

    def is_closed(self):
        return self.closed.is_set()


class Launcher:
    def launch(self, _snapshot):
        return Handle()


def _profile(client, auth_headers):
    response = client.post(
        "/api/v1/profiles",
        headers=auth_headers,
        json={"name": "Runtime API profile"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _seed_runtime_count_states(client):
    profile_ids = {}
    with client.app.state.session_factory() as session:
        for state in (
            "queued",
            "stopped",
            "starting",
            "running",
            "stopping",
            "crashed",
            "detached",
        ):
            profile = Profile(
                name=f"{state} count profile",
                fingerprint_seed=str(abs(hash(f"count {state}")) % 1_000_000_000 + 1),
                fingerprint_config_hash="a" * 64,
            )
            session.add(profile)
            session.flush()
            session.add(RuntimeSession(profile_id=profile.id, state=state, last_message=state))
            profile_ids[state] = profile.id
        deleted = Profile(
            name="deleted running count profile",
            fingerprint_seed=str(abs(hash("deleted count")) % 1_000_000_000 + 1),
            fingerprint_config_hash="a" * 64,
        )
        from datetime import datetime, timezone

        deleted.deleted_at = datetime.now(timezone.utc)
        session.add(deleted)
        session.flush()
        session.add(
            RuntimeSession(profile_id=deleted.id, state="running", last_message="running")
        )
        session.commit()
    return profile_ids


def test_bootstrap_reports_only_live_active_runtime_sessions(client, auth_headers):
    _seed_runtime_count_states(client)

    response = client.get("/api/v1/app/bootstrap", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["running_session_count"] == 3


def _logs(client, auth_headers, profile_id):
    response = client.get(
        f"/api/v1/profiles/{profile_id}/logs",
        headers=auth_headers,
    )
    assert response.status_code == 200
    return response.json()


def _wait_for_log_events(client, auth_headers, profile_id, expected_events):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        payload = _logs(client, auth_headers, profile_id)
        events = {entry["event"] for entry in payload["items"]}
        if expected_events <= events:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"missing log events: {expected_events - events}")


def test_runtime_start_detail_list_and_stop_are_authenticated(client, auth_headers):
    client.app.state.runtime_manager = RuntimeManager(
        client.app.state.session_factory,
        client.app.state.settings,
        launcher=Launcher(),
    )
    profile_id = _profile(client, auth_headers)

    started = client.post(f"/api/v1/profiles/{profile_id}/start", headers=auth_headers)
    assert started.status_code == 202
    runtime_id = started.json()["id"]

    deadline = time.monotonic() + 3
    detail = None
    while time.monotonic() < deadline:
        detail = client.get(f"/api/v1/runtimes/{runtime_id}")
        if detail.status_code == 200 and detail.json()["state"] == "running":
            break
        time.sleep(0.01)
    assert detail is not None and detail.json()["state"] == "running"
    listing = client.get("/api/v1/runtimes")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["items"]] == [runtime_id]

    stopped = client.post(f"/api/v1/profiles/{profile_id}/stop", headers=auth_headers)
    assert stopped.status_code == 202
    client.app.state.runtime_manager.shutdown()


def test_runtime_lifecycle_events_are_exposed_in_authenticated_profile_logs(
    client, auth_headers
):
    client.app.state.runtime_manager = RuntimeManager(
        client.app.state.session_factory,
        client.app.state.settings,
        launcher=Launcher(),
    )
    profile_id = _profile(client, auth_headers)

    started = client.post(f"/api/v1/profiles/{profile_id}/start", headers=auth_headers)
    assert started.status_code == 202
    _wait_for_log_events(
        client,
        auth_headers,
        profile_id,
        {
            "runtime.start_requested",
            "runtime.process_started",
            "runtime.ready",
        },
    )

    stopped = client.post(f"/api/v1/profiles/{profile_id}/stop", headers=auth_headers)
    assert stopped.status_code == 202
    payload = _wait_for_log_events(
        client,
        auth_headers,
        profile_id,
        {"runtime.stop_requested", "runtime.exited"},
    )
    assert payload["total"] == 5
    assert payload["page"] == 1
    assert payload["page_size"] == 50
    client.app.state.runtime_manager.shutdown()


def test_runtime_preflight_and_crash_logs_do_not_expose_secrets(client, auth_headers):
    secret = "socks5://alice:very-secret-password@proxy.example:1080"

    def reject(_snapshot):
        from manager_backend.errors import ManagerError

        raise ManagerError("proxy_preflight_failed", secret, 409)

    client.app.state.runtime_manager = RuntimeManager(
        client.app.state.session_factory,
        client.app.state.settings,
        launcher=Launcher(),
        proxy_preflight=reject,
    )
    preflight_profile_id = _profile(client, auth_headers)
    started = client.post(
        f"/api/v1/profiles/{preflight_profile_id}/start", headers=auth_headers
    )
    assert started.status_code == 202
    preflight_payload = _wait_for_log_events(
        client,
        auth_headers,
        preflight_profile_id,
        {"runtime.start_requested", "runtime.preflight_failed", "runtime.crashed"},
    )
    assert secret not in str(preflight_payload)

    class BrokenLauncher:
        def launch(self, _snapshot):
            raise RuntimeError(secret)

    client.app.state.runtime_manager = RuntimeManager(
        client.app.state.session_factory,
        client.app.state.settings,
        launcher=BrokenLauncher(),
    )
    crash_profile_id = _profile(client, auth_headers)
    started = client.post(
        f"/api/v1/profiles/{crash_profile_id}/start", headers=auth_headers
    )
    assert started.status_code == 202
    crash_payload = _wait_for_log_events(
        client,
        auth_headers,
        crash_profile_id,
        {"runtime.start_requested", "runtime.crashed"},
    )
    assert secret not in str(crash_payload)
    client.app.state.runtime_manager.shutdown()


def test_runtime_reconciliation_events_are_exposed_in_profile_logs(client, auth_headers):
    with client.app.state.session_factory() as session:
        profile = Profile(
            name="Reconciled profile",
            fingerprint_seed="123456",
            fingerprint_config_hash="a" * 64,
        )
        session.add(profile)
        session.commit()
        runtime = create_runtime_session(session, profile)
        transition_runtime(session, runtime, "starting")
        transition_runtime(session, runtime, "running")
        profile_id = profile.id

    class MissingProcess:
        def inspect(self, _runtime, _profile_dir):
            return "missing"

    reconcile_runtimes(
        client.app.state.session_factory,
        client.app.state.settings,
        inspector=MissingProcess(),
    )
    payload = _wait_for_log_events(
        client, auth_headers, profile_id, {"runtime.reconciled"}
    )
    assert payload["items"][0]["event"] == "runtime.reconciled"


def test_profile_logs_require_login_and_limit_page_size(client, auth_headers):
    profile_id = _profile(client, auth_headers)
    response = client.get(
        f"/api/v1/profiles/{profile_id}/logs?page_size=201",
        headers=auth_headers,
    )
    assert response.status_code == 422
    client.cookies.clear()
    assert client.get(f"/api/v1/profiles/{profile_id}/logs").status_code == 401


def test_profile_logs_accept_a_200_row_page_size(client, auth_headers):
    profile_id = _profile(client, auth_headers)
    with client.app.state.session_factory() as session:
        session.add_all(
            [
                ProfileLogEntry(
                    profile_id=profile_id,
                    sequence=sequence,
                    level="info",
                    event="runtime.ready",
                    message="Runtime ready.",
                )
                for sequence in range(1, 201)
            ]
        )
        session.commit()

    response = client.get(
        f"/api/v1/profiles/{profile_id}/logs?page_size=200",
        headers=auth_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["page_size"] == 200
    assert len(payload["items"]) == 200


def test_runtime_routes_require_login(client):
    assert client.get("/api/v1/runtimes").status_code == 401


def test_runtime_snapshot_reports_live_active_runtime_session_count(client, auth_headers):
    _seed_runtime_count_states(client)

    with client.websocket_connect(
        "/api/v1/events",
        headers={"Origin": "http://127.0.0.1:5173"},
    ) as socket:
        snapshot = socket.receive_json()

    assert snapshot["type"] == "runtime.snapshot"
    assert snapshot["running_session_count"] == 3


def test_runtime_snapshot_emits_when_only_running_count_changes(client, auth_headers):
    profile_ids = _seed_runtime_count_states(client)

    with client.websocket_connect(
        "/api/v1/events",
        headers={"Origin": "http://127.0.0.1:5173"},
    ) as socket:
        initial = socket.receive_json()
        assert initial["running_session_count"] == 3

        with client.app.state.session_factory() as session:
            session.get(Profile, profile_ids["running"]).deleted_at = datetime.now(
                timezone.utc
            )
            session.commit()

        changed = socket.receive_json()

    assert changed["sequence"] == initial["sequence"] + 1
    assert changed["type"] == "runtime.snapshot"
    assert changed["running_session_count"] == 2


def test_runtime_snapshot_contains_only_latest_session_per_profile(client, auth_headers):
    with client.app.state.session_factory() as session:
        for profile_index in range(10):
            profile = Profile(
                name=f"history-{profile_index}",
                fingerprint_seed=f"{profile_index + 8000:020x}",
                fingerprint_config_hash="a" * 64,
            )
            session.add(profile)
            session.flush()
            session.add_all(
                [
                    RuntimeSession(
                        profile_id=profile.id,
                        state="stopped",
                        last_message=f"stopped-{runtime_index}",
                    )
                    for runtime_index in range(100)
                ]
            )
        session.commit()

    with client.websocket_connect(
        "/api/v1/events",
        headers={"Origin": "http://127.0.0.1:5173"},
    ) as socket:
        snapshot = socket.receive_json()

    with client.app.state.engine.connect() as connection:
        profile_ids = {
            profile_id
            for profile_id, in connection.exec_driver_sql(
                "SELECT id FROM profiles WHERE name LIKE 'history-%'"
            )
        }
    assert len(snapshot["runtimes"]) == 10
    assert {runtime["profile_id"] for runtime in snapshot["runtimes"]} == profile_ids


def test_runtime_events_require_cookie_and_exact_origin(client, auth_headers):
    client.app.state.runtime_manager = RuntimeManager(
        client.app.state.session_factory,
        client.app.state.settings,
        launcher=Launcher(),
    )
    profile_id = _profile(client, auth_headers)
    with client.websocket_connect(
        "/api/v1/events",
        headers={"Origin": "http://127.0.0.1:5173"},
    ) as socket:
        initial = socket.receive_json()
        assert initial["sequence"] == 1
        assert initial["type"] == "runtime.snapshot"
        client.post(f"/api/v1/profiles/{profile_id}/start", headers=auth_headers)
        event = socket.receive_json()
        assert event["sequence"] > initial["sequence"]
        assert event["type"] == "runtime.snapshot"
        assert any(item["profile_id"] == profile_id for item in event["runtimes"])
    client.app.state.runtime_manager.shutdown()

    try:
        with client.websocket_connect(
            "/api/v1/events", headers={"Origin": "http://evil.invalid"}
        ):
            raise AssertionError("foreign origin was accepted")
    except Exception:
        pass
