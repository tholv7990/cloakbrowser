from __future__ import annotations

from datetime import datetime, timezone

import pytest

from manager_backend.errors import ManagerError
from manager_backend.features.proxies.credentials import MemoryCredentialStore, ProxyCredential
from manager_backend.features.proxies.providers import GeneratedProxy
from manager_backend.features.proxies.testing import ProxyTestFailure, QuickTestResult
from manager_backend.features.shop_check import provisioner
from manager_backend.models import Profile, Proxy, ShopCheckRun, ShopCheckWorker


def _proxy(session, label="sc-proxy") -> str:
    proxy = Proxy(label=label, scheme="socks5h", host="h", port=20000, proxy_type="residential")
    session.add(proxy)
    session.flush()
    return proxy.id


def _worker(session) -> str:
    run = ShopCheckRun(
        status="preparing", emails_per_profile=5, max_parallel=3,
        target_url="https://shop.app/", total_emails=0,
    )
    session.add(run)
    session.flush()
    worker = ShopCheckWorker(run_id=run.id, ordinal=0, state="profile_create", assigned_count=1)
    session.add(worker)
    session.commit()
    return worker.id


def _ok_result() -> QuickTestResult:
    return QuickTestResult(
        exit_ip="203.0.113.5",
        exit_ip_matches=True,
        latency_ms=120,
        checked_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        country="US",
        timezone="America/New_York",
    )


def _configure(store: MemoryCredentialStore) -> None:
    store.put("proxy-provider:seveneleven", ProxyCredential("acct-user", "ACCT-SECRET"))


class FakeProvider:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    def generate(self, provider, credential, count, country, session_type):
        self.calls += 1
        if self.error:
            raise self.error
        return [
            GeneratedProxy(host="global.711proxy.com", port=20000,
                           username=f"u{self.calls}", password="GEN-SECRET")
            for _ in range(count)
        ]


class FakeTester:
    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def run_fast(self, url, timeout_seconds=5):
        item = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


def test_provision_proxy_success_creates_pool_proxy_and_hides_secret(db_session_factory):
    store = MemoryCredentialStore()
    _configure(store)
    proxy_id = provisioner.provision_proxy(
        db_session_factory, store, FakeProvider(), FakeTester([_ok_result()]),
        region="US",
    )
    with db_session_factory() as session:
        proxy = session.get(Proxy, proxy_id)
        assert proxy is not None
        assert proxy.proxy_type == "residential"
        assert proxy.credential_ref
        # secret is in the store, never on the DB row
        assert store.get(proxy.credential_ref).password == "GEN-SECRET"
        row = str(proxy.__dict__)
        assert "GEN-SECRET" not in row and "ACCT-SECRET" not in row


def test_provision_proxy_retries_preflight_then_succeeds(db_session_factory):
    store = MemoryCredentialStore()
    _configure(store)
    provider = FakeProvider()
    tester = FakeTester([ProxyTestFailure("dns_failed"), ProxyTestFailure("dns_failed"), _ok_result()])
    proxy_id = provisioner.provision_proxy(db_session_factory, store, provider, tester, region="US")
    assert proxy_id
    assert provider.calls == 3  # a fresh proxy per attempt


def test_provision_proxy_preflight_exhausted_raises(db_session_factory):
    store = MemoryCredentialStore()
    _configure(store)
    tester = FakeTester([ProxyTestFailure("connection_refused")] * 3)
    with pytest.raises(provisioner.ProxyProvisionError) as e:
        provisioner.provision_proxy(db_session_factory, store, FakeProvider(), tester, region="US")
    assert e.value.category == "preflight_failed"


def test_provision_proxy_timeout_category(db_session_factory):
    store = MemoryCredentialStore()
    _configure(store)
    tester = FakeTester([ProxyTestFailure("timeout")] * 3)
    with pytest.raises(provisioner.ProxyProvisionError) as e:
        provisioner.provision_proxy(db_session_factory, store, FakeProvider(), tester, region="US")
    assert e.value.category == "timeout"


def test_provision_proxy_credential_missing(db_session_factory):
    store = MemoryCredentialStore()  # provider NOT configured
    with pytest.raises(provisioner.ProxyProvisionError) as e:
        provisioner.provision_proxy(db_session_factory, store, FakeProvider(), FakeTester([_ok_result()]), region="US")
    assert e.value.category == "credential_missing"


def test_provision_proxy_provider_unavailable(db_session_factory):
    store = MemoryCredentialStore()
    _configure(store)
    provider = FakeProvider(error=ConnectionError("boom"))
    with pytest.raises(provisioner.ProxyProvisionError) as e:
        provisioner.provision_proxy(db_session_factory, store, provider, FakeTester([_ok_result()]), region="US")
    assert e.value.category == "provider_unavailable"


def test_provision_proxy_cancelled_before_generation(db_session_factory):
    store = MemoryCredentialStore()
    _configure(store)
    with pytest.raises(provisioner.ProxyProvisionError) as e:
        provisioner.provision_proxy(
            db_session_factory, store, FakeProvider(), FakeTester([_ok_result()]),
            region="US", is_cancelled=lambda: True,
        )
    assert e.value.category == "cancelled"


# --- profile + durable ownership (Task 3) -----------------------------------
def test_provision_profile_creates_owned_profile(db_session_factory):
    with db_session_factory() as session:
        worker_id = _worker(session)
        proxy_id = _proxy(session)
        session.commit()
        profile_id = provisioner.provision_profile(
            session, worker_id, proxy_id=proxy_id, target_url="https://shop.app/", name="sc-0"
        )
    with db_session_factory() as session:
        worker = session.get(ShopCheckWorker, worker_id)
        assert worker.profile_id == profile_id
        assert worker.proxy_id == proxy_id
        profile = session.get(Profile, profile_id)
        assert profile is not None
        assert profile.startup_urls == ["https://shop.app/"]
        assert profile.proxy_id == proxy_id


def test_provision_profile_is_idempotent(db_session_factory):
    with db_session_factory() as session:
        worker_id = _worker(session)
        proxy_id = _proxy(session)
        session.commit()
        pid1 = provisioner.provision_profile(
            session, worker_id, proxy_id=proxy_id, target_url="https://shop.app/", name="sc-0"
        )
    with db_session_factory() as session:
        proxy_id = session.query(Proxy).one().id
        pid2 = provisioner.provision_profile(
            session, worker_id, proxy_id=proxy_id, target_url="https://shop.app/", name="sc-0"
        )
    assert pid1 == pid2
    with db_session_factory() as session:
        assert session.query(Profile).count() == 1


def test_provision_profile_completes_after_ownership_only_crash(db_session_factory):
    # Simulate a crash after ownership was recorded but before the profile existed.
    with db_session_factory() as session:
        worker_id = _worker(session)
        proxy_id = _proxy(session)
        orphan_id = "orphan-profile-id"
        session.get(ShopCheckWorker, worker_id).profile_id = orphan_id
        session.commit()
    with db_session_factory() as session:
        proxy_id = session.query(Proxy).one().id
        result = provisioner.provision_profile(
            session, worker_id, proxy_id=proxy_id, target_url="https://shop.app/", name="sc-0"
        )
        assert result == orphan_id  # reused the recorded ownership id
        assert session.get(Profile, orphan_id) is not None  # profile now exists
