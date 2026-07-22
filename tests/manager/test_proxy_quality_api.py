from __future__ import annotations

from datetime import datetime, timezone

from manager_backend.features.proxies.credentials import MemoryCredentialStore
from manager_backend.models import Proxy, ProxyQualityRun
from manager_backend.features.proxies.quality import recover_orphan_quality_runs


def _proxy(client, auth_headers):
    client.app.state.credential_store = MemoryCredentialStore()
    response = client.post(
        "/api/v1/proxies",
        headers=auth_headers,
        json={
            "label": "Quality proxy",
            "scheme": "socks5",
            "host": "198.51.100.25",
            "port": 50101,
            "username": "fixture-user",
            "password": "fixture-pass",
            "test_before_launch": True,
        },
    )
    assert response.status_code == 201
    return response.json()


def _safe_report(run_id, proxy_id):
    finding = {"status": "aligned", "detail": "Observed values align."}
    return {
        "id": run_id,
        "proxy_id": proxy_id,
        "state": "completed",
        "proxy_type": "residential",
        "type_confidence": 0.91,
        "reputation": "clean",
        "matched_lists": [],
        "google_outcome": "passed",
        "turnstile_outcome": "passed",
        "alignment": {
            "http": finding,
            "webrtc": finding,
            "dns": finding,
            "timezone": finding,
            "locale": finding,
        },
        "latency_ms": 184,
        "exit_ip": "74.0.96.143",
        "country": "US",
        "city": "Dallas",
        "timezone": "America/Chicago",
        "asn": "AS212238",
        "organization": "Datacamp Limited",
        "screenshot_path": None,
        "report_path": None,
        "observed_scope": "Timestamped observation; not a permanent cleanliness guarantee.",
        "checked_at": "2026-07-21T00:00:00Z",
    }


def test_quality_run_and_report_routes_return_sanitized_report(client, auth_headers):
    proxy = _proxy(client, auth_headers)

    class ImmediateManager:
        def submit(self, run_id):
            with client.app.state.session_factory() as session:
                run = session.get(ProxyQualityRun, run_id)
                run.state = "completed"
                run.report = _safe_report(run.id, run.proxy_id)
                run.checked_at = datetime(2026, 7, 21, tzinfo=timezone.utc)
                session.commit()

        def shutdown(self):
            return None

    client.app.state.proxy_quality_manager = ImmediateManager()
    response = client.post(
        f"/api/v1/proxies/{proxy['id']}/quality-test", headers=auth_headers
    )
    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "completed"
    assert "fixture-pass" not in str(body)
    assert client.get(f"/api/v1/proxies/{proxy['id']}/reports").json() == [body]
    assert client.get(f"/api/v1/proxy-reports/{body['id']}").json() == body


def test_only_one_active_quality_run_is_allowed(client, auth_headers):
    proxy = _proxy(client, auth_headers)

    class QueuedManager:
        def submit(self, _run_id):
            return None

        def shutdown(self):
            return None

    client.app.state.proxy_quality_manager = QueuedManager()
    first = client.post(f"/api/v1/proxies/{proxy['id']}/quality-test", headers=auth_headers)
    assert first.status_code == 202
    second = client.post(f"/api/v1/proxies/{proxy['id']}/quality-test", headers=auth_headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "proxy_quality_already_running"


def test_restart_marks_orphaned_quality_runs_failed(db_session_factory):
    with db_session_factory() as session:
        proxy = Proxy(label="Orphan", scheme="direct", test_before_launch=True)
        run = ProxyQualityRun(proxy=proxy, state="running", last_message="running")
        session.add(run)
        session.commit()
        run_id = run.id
    assert recover_orphan_quality_runs(db_session_factory) == 1
    with db_session_factory() as session:
        stored = session.get(ProxyQualityRun, run_id)
        assert stored.state == "failed"
        assert stored.last_message == "manager_restarted"
