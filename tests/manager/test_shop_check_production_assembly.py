"""Production wiring: the REAL app must install a working email processor.

These assertions guard the release-blocking defect where production built the
coordinator with no process_worker and silently completed workers while leaving
every email pending. We construct the real app (no fixture swap of the
coordinator) and drive one worker with fake runtime/CDP dependencies.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from manager_backend.features.proxies.credentials import MemoryCredentialStore, ProxyCredential
from manager_backend.features.proxies.providers import GeneratedProxy
from manager_backend.features.proxies.testing import QuickTestResult
from manager_backend.features.shop_check import coordinator as coordinator_module
from manager_backend.features.shop_check import service
from manager_backend.features.shop_check.schemas import ShopCheckRunCreate
from manager_backend.main import create_app
from manager_backend.models import ShopCheckEmail

_TERMINAL = {"completed", "completed_with_issues", "cancelled", "failed"}
_ACCOUNT_NOT_FOUND = "<p>We couldn't find an account with that email address.</p>"


class _FakeProvider:
    def generate(self, provider, credential, count, country, session_type):
        return [GeneratedProxy("global.711proxy.com", 20000, "u", "SECRET") for _ in range(count)]


class _FakeTester:
    def run_fast(self, url, timeout_seconds=5):
        return QuickTestResult("203.0.113.5", True, 100, datetime(2026, 7, 30, tzinfo=timezone.utc))


class _FakeLauncher:
    def start_and_wait_ready(self, profile_id, *, timeout_seconds, is_cancelled):
        return f"cdp://{profile_id}"

    def stop(self, profile_id):
        pass


class _FakeCdpSession:
    """Stands in for CdpShopSession — proves the REAL open_cdp_session path runs
    (it is constructed with the ctx's CDP endpoint) without a browser."""

    instances: list[str] = []

    def __init__(self, cdp_endpoint):
        _FakeCdpSession.instances.append(cdp_endpoint)

    def goto(self, url):
        pass

    def fill_email(self, email):
        pass

    def submit(self):
        pass

    def page_html(self):
        return _ACCOUNT_NOT_FOUND

    def phone_hint(self):
        return None

    def clear_origin_state(self):
        pass

    def screenshot(self):
        return None

    def close(self):
        pass


def test_no_noop_processor_fallback_exists():
    # The silent no-op fallback must be gone: production can never install it.
    assert not hasattr(coordinator_module, "_noop_process_worker")


def test_production_coordinator_checks_emails_end_to_end(settings, monkeypatch):
    app = create_app(settings)
    coordinator = app.state.shop_check_coordinator

    # A real processor is installed (the make_process_worker closure), not a no-op.
    assert coordinator._process_worker.__name__ == "process_worker"

    # Drive one worker with fakes: no network proxy gen, no real browser/CDP.
    store = MemoryCredentialStore()
    store.put("proxy-provider:seveneleven", ProxyCredential("acct", "ACCT"))
    app.state.credential_store = store
    coordinator._store = store
    coordinator._provider_client = _FakeProvider()
    coordinator._tester = _FakeTester()
    coordinator._launcher = _FakeLauncher()
    _FakeCdpSession.instances.clear()
    monkeypatch.setattr(
        "manager_backend.features.shop_check.browser.CdpShopSession", _FakeCdpSession
    )

    session_factory = app.state.session_factory
    with session_factory() as session:
        payload = ShopCheckRunCreate(
            email_text="a@example.com\nb@example.com",
            emails_per_profile=5,
            max_parallel=1,
            authorized_only_ack=True,
        )
        run_id = service.create_run(session, store, payload, session_factory)["run"]["id"]

    try:
        with session_factory() as session:
            coordinator.start(session, run_id)
        deadline = time.monotonic() + 15
        detail = None
        while time.monotonic() < deadline:
            with session_factory() as session:
                detail = service.get_run_detail(session, run_id)
            if detail["status"] in _TERMINAL:
                break
            time.sleep(0.02)

        # The run reached a terminal status (not stuck 'running' forever) ...
        assert detail["status"] in _TERMINAL
        # ... and every assigned email got a terminal result — the exact failure
        # (worker terminal while emails stay pending) must NOT happen.
        with session_factory() as session:
            emails = session.query(ShopCheckEmail).filter_by(run_id=run_id).all()
        assert emails and all(e.state == "terminal" and e.result for e in emails)
        # The real opener (open_cdp_session) ran, constructed with the CDP
        # endpoint that readiness returned.
        assert _FakeCdpSession.instances
        assert all(ep.startswith("cdp://") for ep in _FakeCdpSession.instances)
    finally:
        coordinator.shutdown()
