from __future__ import annotations

from datetime import datetime, timedelta, timezone

from manager_backend.models import RuntimeSession


def test_resources_snapshot_shape(client, auth_headers):
    response = client.get("/api/v1/resources", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"generated_at", "system", "backend", "browsers", "profiles"}
    assert body["system"]["logical_cpus"] >= 1
    assert set(body["system"]) == {
        "cpu_percent",
        "memory_percent",
        "memory_used_bytes",
        "memory_total_bytes",
        "logical_cpus",
    }
    # No profile browsers are running in the test process.
    assert body["browsers"]["profiles_running"] == 0
    assert body["profiles"] == []


def test_sessions_empty(client, auth_headers):
    response = client.get("/api/v1/sessions", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_sessions_maps_a_terminal_runtime(client, auth_headers):
    created = client.post(
        "/api/v1/profiles", headers=auth_headers, json={"name": "Sess Profile"}
    )
    assert created.status_code == 201, created.text
    profile_id = created.json()["id"]

    started = datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc)
    stopped = started + timedelta(seconds=90)
    with client.app.state.session_factory() as session:
        session.add(
            RuntimeSession(
                profile_id=profile_id,
                state="stopped",
                started_at=started,
                stopped_at=stopped,
                last_message="stopped",
            )
        )
        session.commit()

    response = client.get("/api/v1/sessions", headers=auth_headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["profile_name"] == "Sess Profile"
    assert row["exit_reason"] == "stopped"
    assert row["duration_seconds"] == 90
    assert row["ended_at"] is not None
