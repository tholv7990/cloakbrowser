from __future__ import annotations

import threading
import time

from manager_backend.features.runtime.manager import RuntimeManager


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


def test_runtime_routes_require_login(client):
    assert client.get("/api/v1/runtimes").status_code == 401


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
