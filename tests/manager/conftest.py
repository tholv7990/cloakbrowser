from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from manager_backend.config import ManagerSettings
from manager_backend.main import create_app


@pytest.fixture
def settings(tmp_path):
    return ManagerSettings(
        data_root=tmp_path / "manager-data",
        allowed_origin="http://127.0.0.1:5173",
        install_token="test-local-token",
    )


@pytest.fixture
def db_session_factory(settings):
    from manager_backend.db import create_engine_for, create_session_factory
    from manager_backend.models import Base

    engine = create_engine_for(settings)
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(client):
    response = client.post(
        "/api/v1/auth/setup",
        headers={"Origin": "http://127.0.0.1:5173"},
        json={
            "email": "owner@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 201
    return {
        "Origin": "http://127.0.0.1:5173",
        "X-CSRF-Token": response.json()["csrf_token"],
    }
