from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cloakbrowser.config import get_chromium_version

from .harness import (
    AuthenticatedApiClient,
    E2EReport,
    existing_owner_credentials,
    start_manager_stack,
)


@pytest.fixture
def manager_stack(tmp_path):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_root = Path("artifacts/manager-e2e") / f"{stamp}-{os.getpid()}"
    stack = start_manager_stack(tmp_path / "owned", report_root)
    try:
        yield stack
    finally:
        stack.cleanup(stack.cleanup_client)


@pytest.fixture
def authenticated_client(manager_stack):
    client = AuthenticatedApiClient(manager_stack.backend_url, manager_stack.origin)
    client.setup(manager_stack.credentials)
    client.logout()
    client.login(manager_stack.credentials)
    manager_stack.cleanup_client = client
    try:
        yield client
    finally:
        # ManagerStack owns process-aware cleanup; this fixture only makes the client
        # available to dependent finalizers.
        pass


@pytest.fixture
def disposable_profile(manager_stack, authenticated_client):
    response = authenticated_client.post(
        "/profiles",
        json={
            "name": f"Manager E2E {os.getpid()}",
            "fingerprint_preset": "consistent",
            "startup_urls": [],
            "test_proxy_before_launch": True,
        },
    )
    assert response.status_code == 201, response.text
    profile = response.json()
    manager_stack.resources.track_profile(profile["id"])
    return profile


@pytest.fixture
def e2e_report(manager_stack):
    report = E2EReport(
        manager_stack.report_root,
        {
            "platform": "windows",
            "browser_version": get_chromium_version(),
            "browser_tier": "installed",
            "resources": manager_stack.resources.report_metadata(),
        },
    )
    manager_stack.report = report
    yield report


@pytest.fixture
def existing_owner_client():
    credentials = existing_owner_credentials()
    base_url = os.environ.get("CLOAK_MANAGER_BASE_URL", "http://127.0.0.1:8765")
    origin = os.environ.get("CLOAK_MANAGER_ORIGIN", "http://127.0.0.1:5273")
    client = AuthenticatedApiClient(base_url, origin)
    try:
        client.login(credentials)
        yield client
    finally:
        client.close()
