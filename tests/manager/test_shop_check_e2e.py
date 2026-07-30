"""POST /runs really provisions, end to end over HTTP.

The coordinator is the real one; only the proxy provider, the quick tester and
the browser launcher are faked, so this covers HTTP -> claim -> group -> proxy
-> profile+ownership -> launch -> process -> recompute without touching the
network or spawning a browser.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import pytest

from manager_backend.features.proxies.credentials import (
    MemoryCredentialStore,
    ProxyCredential,
)
from manager_backend.features.proxies.providers import GeneratedProxy
from manager_backend.features.proxies.testing import QuickTestResult
from manager_backend.features.shop_check import service
from manager_backend.features.shop_check.coordinator import ShopCheckCoordinator
from manager_backend.models import ShopCheckEmail

_BASE = "/api/v1/automations/shop-check"
_TERMINAL = {"completed", "completed_with_issues", "cancelled", "failed"}
SENTINEL = "sentinel.person@corp-example.com"


class FakeProvider:
    def generate(self, provider, credential, count, country, session_type):
        return [
            GeneratedProxy("global.711proxy.com", 20000, "puser", "GEN-SECRET")
            for _ in range(count)
        ]


class FakeTester:
    def run_fast(self, url, timeout_seconds=5):
        return QuickTestResult(
            "203.0.113.5", True, 100, datetime(2026, 7, 29, tzinfo=timezone.utc)
        )


class FakeLauncher:
    def __init__(self):
        self.started: list[str] = []
        self.stopped: list[str] = []
        self._lock = threading.Lock()

    def start(self, profile_id):
        with self._lock:
            self.started.append(profile_id)

    def stop(self, profile_id):
        with self._lock:
            self.stopped.append(profile_id)


def _finalize_all(ctx):
    """Stand-in for the later browser checkpoint: terminate every assigned email."""
    with ctx.session_factory() as session:
        for email_id in ctx.email_ids:
            service.finalize_email(
                session, session.get(ShopCheckEmail, email_id), "login_success"
            )


@pytest.fixture
def launcher(client):
    store = MemoryCredentialStore()
    store.put("proxy-provider:seveneleven", ProxyCredential("acct", "ACCT-SECRET"))
    client.app.state.credential_store = store
    fake = FakeLauncher()
    client.app.state.shop_check_coordinator = ShopCheckCoordinator(
        client.app.state.session_factory,
        store,
        FakeProvider(),
        FakeTester(),
        fake,
        process_worker=_finalize_all,
    )
    yield fake
    client.app.state.shop_check_coordinator.shutdown()


def _create(client, auth_headers, email_text: str):
    return client.post(
        f"{_BASE}/runs",
        headers=auth_headers,
        json={
            "email_text": email_text,
            "emails_per_profile": 5,
            "max_parallel": 3,
            "authorized_only_ack": True,
        },
    )


def _emails(count: int) -> str:
    return "\n".join(f"user{i}@example.com" for i in range(count))


def _wait(client, auth_headers, run_id: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        detail = client.get(f"{_BASE}/runs/{run_id}", headers=auth_headers).json()
        if detail["status"] in _TERMINAL or time.monotonic() > deadline:
            return detail
        time.sleep(0.02)


def test_create_provisions_workers_through_the_coordinator(
    client, auth_headers, launcher
):
    response = _create(client, auth_headers, _emails(10))  # 2 workers
    assert response.status_code == 202, response.text
    # The claim is synchronous in the request, so the run is already handed off.
    assert response.json()["run"]["status"] != "queued"

    detail = _wait(client, auth_headers, response.json()["run"]["id"])
    assert detail["status"] == "completed"
    assert detail["terminal_count"] == 10
    workers = detail["workers"]
    assert len(workers) == 2
    assert all(worker["state"] == "terminal" for worker in workers)
    # Every worker owns a provisioned proxy + profile, and that profile is what
    # got launched (and stopped) — the run reached launching/processing for real.
    owned = sorted(worker["profile_id"] for worker in workers)
    assert all(worker["proxy_id"] for worker in workers)
    assert sorted(launcher.started) == owned
    assert sorted(launcher.stopped) == owned


def test_no_secret_leaks_through_the_api_after_provisioning(
    client, auth_headers, launcher
):
    created = _create(client, auth_headers, SENTINEL)
    run_id = created.json()["run"]["id"]
    _wait(client, auth_headers, run_id)
    blobs = [
        created.text,
        client.get(f"{_BASE}/runs", headers=auth_headers).text,
        client.get(f"{_BASE}/runs/{run_id}", headers=auth_headers).text,
        client.get(f"{_BASE}/runs/{run_id}/emails", headers=auth_headers).text,
    ]
    for blob in blobs:
        assert SENTINEL not in blob
        assert "ACCT-SECRET" not in blob and "GEN-SECRET" not in blob
        assert "credential_ref" not in blob
        assert "email_fingerprint" not in blob


def test_failed_handoff_keeps_the_created_run(client, auth_headers):
    """A hand-off failure must never 500: the run is already durably persisted,
    and a 500 would invite a duplicate-run retry (double provisioning)."""

    class Boom:
        def start(self, session, run_id):
            raise RuntimeError(f"kaboom {SENTINEL}")

        def shutdown(self, timeout=10.0):  # called by the app's lifespan teardown
            return True

    client.app.state.credential_store = MemoryCredentialStore()
    client.app.state.shop_check_coordinator = Boom()

    response = _create(client, auth_headers, SENTINEL)
    assert response.status_code == 202, response.text
    assert SENTINEL not in response.text
    run_id = response.json()["run"]["id"]
    listing = client.get(f"{_BASE}/runs", headers=auth_headers).json()
    assert run_id in [run["id"] for run in listing["items"]]
