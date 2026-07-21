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
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-local-token"}
