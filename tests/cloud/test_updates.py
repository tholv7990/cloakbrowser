from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from cloud.app import create_app
from cloud.config import generate_test_settings
from cloud.db import Base, create_engine_for, create_session_factory, utc_now
from cloud.features.updates.service import get_latest_release, publish_release


@pytest.fixture
def env(tmp_path):
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    client = TestClient(create_app(generate_test_settings(), session_factory=factory))
    return factory, client


def _publish(session, *, channel, version, published_at):
    release = publish_release(
        session,
        channel=channel,
        version=version,
        min_supported_version="1.0.0",
        artifact_url=f"https://downloads.example/{version}",
        sha256="a" * 64,
        signature=f"sig-{version}",
    )
    release.published_at = published_at
    return release


def test_get_latest_release_is_newest_per_channel(env):
    factory, _client = env
    now = utc_now()
    with factory() as session:
        _publish(session, channel="stable", version="1.0.0", published_at=now - timedelta(days=2))
        _publish(session, channel="stable", version="1.1.0", published_at=now - timedelta(days=1))
        _publish(session, channel="beta", version="1.2.0-beta", published_at=now)
        session.commit()
    with factory() as session:
        assert get_latest_release(session, channel="stable").version == "1.1.0"
        assert get_latest_release(session, channel="beta").version == "1.2.0-beta"


def test_updates_latest_route_returns_the_signed_manifest(env):
    factory, client = env
    now = utc_now()
    with factory() as session:
        _publish(session, channel="stable", version="1.1.0", published_at=now)
        session.commit()

    resp = client.get("/updates/latest", params={"channel": "stable"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "1.1.0"
    assert body["min_supported_version"] == "1.0.0"
    assert body["sha256"] == "a" * 64
    assert body["signature"] == "sig-1.1.0"


def test_updates_latest_404s_when_no_release_or_bad_channel(env):
    _factory, client = env
    assert client.get("/updates/latest", params={"channel": "stable"}).status_code == 404
    assert client.get("/updates/latest", params={"channel": "nonsense"}).status_code == 404


def test_is_newer_numeric_dotted_compare():
    from cloud.features.updates.service import is_newer

    assert is_newer("1.1.0", "1.0.0") is True
    assert is_newer("2.0.0", "1.9.9") is True
    assert is_newer("v1.2.0", "1.1.9") is True  # leading v tolerated
    assert is_newer("1.0.0", "1.0.0") is False
    assert is_newer("1.0.0", "1.1.0") is False


def test_tauri_update_returns_manifest_when_newer(env):
    factory, client = env
    now = utc_now()
    with factory() as session:
        _publish(session, channel="stable", version="1.1.0", published_at=now)
        session.commit()

    resp = client.get("/updates/tauri/windows-x86_64/1.0.0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == "1.1.0"
    assert body["url"] == "https://downloads.example/1.1.0"
    assert body["signature"] == "sig-1.1.0"
    assert "pub_date" in body


def test_tauri_update_204_when_up_to_date_or_client_ahead(env):
    factory, client = env
    now = utc_now()
    with factory() as session:
        _publish(session, channel="stable", version="1.1.0", published_at=now)
        session.commit()
    assert client.get("/updates/tauri/windows-x86_64/1.1.0").status_code == 204
    assert client.get("/updates/tauri/windows-x86_64/2.0.0").status_code == 204


def test_tauri_update_204_when_no_release(env):
    _factory, client = env
    assert client.get("/updates/tauri/windows-x86_64/1.0.0").status_code == 204
