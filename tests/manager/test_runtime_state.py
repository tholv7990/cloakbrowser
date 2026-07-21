from __future__ import annotations

import pytest

from manager_backend.errors import ManagerError
from manager_backend.features.runtime.service import (
    create_runtime_session,
    transition_runtime,
)
from manager_backend.models import Profile


def _profile(db_session_factory):
    session = db_session_factory()
    profile = Profile(
        name="Runtime profile",
        fingerprint_seed="99112233",
        fingerprint_config_hash="a" * 64,
    )
    session.add(profile)
    session.commit()
    return session, profile


def test_runtime_session_transitions_and_profile_state(db_session_factory):
    session, profile = _profile(db_session_factory)
    try:
        runtime = create_runtime_session(session, profile)
        assert runtime.state == "queued"
        transition_runtime(session, runtime, "starting")
        transition_runtime(session, runtime, "running")
        assert profile.runtime_state == "running"
        transition_runtime(session, runtime, "stopping")
        transition_runtime(session, runtime, "stopped")
        assert profile.runtime_state == "stopped"
        assert runtime.stopped_at is not None
    finally:
        session.close()


def test_runtime_rejects_invalid_transition(db_session_factory):
    session, profile = _profile(db_session_factory)
    try:
        runtime = create_runtime_session(session, profile)
        with pytest.raises(ManagerError) as error:
            transition_runtime(session, runtime, "running")
        assert error.value.code == "invalid_runtime_transition"
    finally:
        session.close()


def test_only_one_active_runtime_per_profile(db_session_factory):
    session, profile = _profile(db_session_factory)
    try:
        create_runtime_session(session, profile)
        with pytest.raises(ManagerError) as error:
            create_runtime_session(session, profile)
        assert error.value.code == "profile_already_running"
        assert error.value.status_code == 409
    finally:
        session.close()


def test_trashed_profile_cannot_start(db_session_factory):
    session, profile = _profile(db_session_factory)
    try:
        from manager_backend.models import utc_now

        profile.deleted_at = utc_now()
        session.commit()
        with pytest.raises(ManagerError) as error:
            create_runtime_session(session, profile)
        assert error.value.code == "profile_trashed"
    finally:
        session.close()


def test_profile_api_uses_runtime_session_state(client, auth_headers):
    created = client.post(
        "/api/v1/profiles",
        headers=auth_headers,
        json={"name": "Runtime API"},
    ).json()
    with client.app.state.session_factory() as session:
        profile = session.get(Profile, created["id"])
        create_runtime_session(session, profile)
    response = client.get(f"/api/v1/profiles/{created['id']}", headers=auth_headers)
    assert response.json()["runtime_state"] == "queued"
