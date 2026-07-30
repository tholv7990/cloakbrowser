from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from manager_backend.config import ManagerSettings
from manager_backend.features.shop_check import service as shop_check_service
from manager_backend.main import create_app


class InertShopCheckCoordinator:
    """Records run hand-offs, spawns nothing.

    POST /runs hands a created run to the coordinator, but ordinary API tests
    must never provision proxies, create profiles, or launch browsers. Real
    orchestration through HTTP is covered by test_shop_check_e2e.py, which
    installs a real coordinator wired to fakes.
    """

    def __init__(self):
        self.started: list[str] = []

    def start(self, session, run_id: str) -> dict:
        self.started.append(run_id)
        return shop_check_service.get_run_detail(session, run_id)

    def cancel(self, session, run_id: str) -> dict:
        return shop_check_service.cancel_run(session, run_id)

    def recover(self, session_factory=None) -> int:
        return 0

    def shutdown(self, timeout: float = 10.0) -> bool:
        return True


@pytest.fixture
def settings(tmp_path):
    return ManagerSettings(
        data_root=tmp_path / "manager-data",
        allowed_origin="http://127.0.0.1:5173",
        install_token="test-local-token",
        auto_backup_enabled=False,
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
    app = create_app(settings)
    app.state.shop_check_coordinator = InertShopCheckCoordinator()
    with TestClient(app) as test_client:
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
