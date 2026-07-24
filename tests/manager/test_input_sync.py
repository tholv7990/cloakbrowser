"""Phase B input sync: captured control-page events -> CDP commands for followers."""

from __future__ import annotations

from manager_backend.features.runtime.input_sync import InputSyncService, translate_event


def test_click_translates_to_mouse_dispatch_at_the_same_viewport_point():
    commands = translate_event(
        {"kind": "mouse", "type": "mousePressed", "x": 120, "y": 240, "button": 0}
    )
    assert commands == [
        (
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": 120.0,
                "y": 240.0,
                "button": "left",
                "clickCount": 1,
            },
        )
    ]


def test_right_and_middle_buttons_map_to_their_cdp_names():
    right = translate_event({"kind": "mouse", "type": "mouseReleased", "x": 1, "y": 2, "button": 2})
    middle = translate_event({"kind": "mouse", "type": "mousePressed", "x": 1, "y": 2, "button": 1})
    assert right[0][1]["button"] == "right"
    assert middle[0][1]["button"] == "middle"


def test_printable_key_carries_text_so_the_keystroke_actually_types():
    method, params = translate_event(
        {"kind": "key", "type": "keyDown", "key": "a", "code": "KeyA", "keyCode": 65, "text": "a"}
    )[0]
    assert method == "Input.dispatchKeyEvent"
    assert params["type"] == "keyDown"
    assert params["text"] == "a"
    assert params["key"] == "a"
    assert params["code"] == "KeyA"
    assert params["windowsVirtualKeyCode"] == 65


def test_non_printable_key_omits_text():
    # Enter/Backspace/arrows must NOT carry text, or they'd insert junk characters.
    _, params = translate_event(
        {"kind": "key", "type": "keyDown", "key": "Enter", "code": "Enter", "keyCode": 13, "text": ""}
    )[0]
    assert "text" not in params
    assert params["key"] == "Enter"


def test_wheel_translates_to_a_mouse_wheel_dispatch_with_deltas():
    method, params = translate_event(
        {"kind": "wheel", "x": 10, "y": 20, "dx": 0, "dy": 120}
    )[0]
    assert method == "Input.dispatchMouseEvent"
    assert params["type"] == "mouseWheel"
    assert params["deltaY"] == 120.0


def test_unknown_or_malformed_events_yield_no_commands():
    # A malformed payload must never raise into the fanout loop.
    assert translate_event({"kind": "bogus"}) == []
    assert translate_event({}) == []
    assert translate_event({"kind": "mouse", "type": "mouseMoved", "x": 1, "y": 1}) == []
    assert translate_event({"kind": "key", "type": "char", "key": "a"}) == []


def test_status_reports_inactive_before_any_session():
    service = InputSyncService()
    assert service.status() == {
        "active": False,
        "control_profile_id": None,
        "follower_profile_ids": [],
    }


# --- routes -----------------------------------------------------------------

from manager_backend.models import Profile, RuntimeSession  # noqa: E402


class FakeSyncService:
    """Stands in for the CDP-connecting service so route tests stay hermetic."""

    def __init__(self):
        self.active = False
        self.started_with: dict | None = None
        self.control_profile_id = None
        self.follower_profile_ids: list[str] = []

    async def start(self, *, control_profile_id, control_endpoint, followers):
        self.started_with = {
            "control_profile_id": control_profile_id,
            "control_endpoint": control_endpoint,
            "followers": followers,
        }
        self.active = True
        self.control_profile_id = control_profile_id
        self.follower_profile_ids = [pid for pid, _ in followers]

    async def stop(self):
        self.active = False
        self.control_profile_id = None
        self.follower_profile_ids = []

    def status(self):
        return {
            "active": self.active,
            "control_profile_id": self.control_profile_id,
            "follower_profile_ids": list(self.follower_profile_ids),
        }


def _running_profile(client, name: str, endpoint: str | None) -> str:
    with client.app.state.session_factory() as session:
        profile = Profile(
            name=name,
            fingerprint_seed=str(abs(hash(name)) % 1_000_000_000 + 1),
            fingerprint_config_hash="a" * 64,
        )
        session.add(profile)
        session.flush()
        session.add(
            RuntimeSession(
                profile_id=profile.id,
                state="running",
                last_message="running",
                cdp_endpoint=endpoint,
            )
        )
        session.commit()
        return profile.id


def test_sync_start_mirrors_control_to_followers_and_never_to_itself(client, auth_headers):
    fake = FakeSyncService()
    client.app.state.input_sync = fake
    control = _running_profile(client, "sync control", "http://127.0.0.1:1111")
    follower = _running_profile(client, "sync follower", "http://127.0.0.1:2222")

    response = client.post(
        "/api/v1/runtime/sync/start",
        headers=auth_headers,
        json={
            "control_profile_id": control,
            # the control id is included here on purpose: it must be filtered out
            "follower_profile_ids": [control, follower],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "active": True,
        "control_profile_id": control,
        "follower_profile_ids": [follower],
    }
    assert fake.started_with["control_endpoint"] == "http://127.0.0.1:1111"
    assert fake.started_with["followers"] == [(follower, "http://127.0.0.1:2222")]


def test_sync_start_409s_when_the_control_profile_has_no_endpoint(client, auth_headers):
    client.app.state.input_sync = FakeSyncService()
    # Started before Phase B (no endpoint recorded) -> needs a relaunch, not a crash.
    control = _running_profile(client, "sync legacy control", None)
    follower = _running_profile(client, "sync legacy follower", "http://127.0.0.1:2222")

    response = client.post(
        "/api/v1/runtime/sync/start",
        headers=auth_headers,
        json={"control_profile_id": control, "follower_profile_ids": [follower]},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "input_sync_unavailable"


def test_sync_start_409s_when_no_follower_can_be_synced(client, auth_headers):
    client.app.state.input_sync = FakeSyncService()
    control = _running_profile(client, "sync lonely control", "http://127.0.0.1:1111")
    follower = _running_profile(client, "sync lonely follower", None)

    response = client.post(
        "/api/v1/runtime/sync/start",
        headers=auth_headers,
        json={"control_profile_id": control, "follower_profile_ids": [follower]},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "input_sync_no_followers"


def test_sync_status_and_stop_round_trip(client, auth_headers):
    fake = FakeSyncService()
    client.app.state.input_sync = fake
    control = _running_profile(client, "sync rt control", "http://127.0.0.1:1111")
    follower = _running_profile(client, "sync rt follower", "http://127.0.0.1:2222")

    assert client.get("/api/v1/runtime/sync/status", headers=auth_headers).json()["active"] is False

    client.post(
        "/api/v1/runtime/sync/start",
        headers=auth_headers,
        json={"control_profile_id": control, "follower_profile_ids": [follower]},
    )
    assert client.get("/api/v1/runtime/sync/status", headers=auth_headers).json()["active"] is True

    stopped = client.post("/api/v1/runtime/sync/stop", headers=auth_headers)
    assert stopped.status_code == 200
    assert stopped.json()["active"] is False
    assert client.get("/api/v1/runtime/sync/status", headers=auth_headers).json()["active"] is False


def test_sync_start_409s_when_a_session_is_already_active(client, auth_headers):
    fake = FakeSyncService()
    fake.active = True
    client.app.state.input_sync = fake
    control = _running_profile(client, "sync busy control", "http://127.0.0.1:1111")

    response = client.post(
        "/api/v1/runtime/sync/start",
        headers=auth_headers,
        json={"control_profile_id": control, "follower_profile_ids": []},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "input_sync_already_active"
