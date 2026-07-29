from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from manager_backend.features.proxies.credentials import MemoryCredentialStore, ProxyCredential
from manager_backend.features.proxies.providers import GeneratedProxy
from manager_backend.features.proxies.testing import ProxyTestFailure, QuickTestResult
from manager_backend.features.shop_check import service
from manager_backend.features.shop_check.coordinator import ShopCheckCoordinator
from manager_backend.features.shop_check.schemas import ShopCheckRunCreate
from manager_backend.models import ShopCheckEmail, ShopCheckWorker

_TERMINAL = {"completed", "completed_with_issues", "cancelled", "failed"}


def _ok():
    return QuickTestResult("203.0.113.5", True, 100, datetime(2026, 7, 29, tzinfo=timezone.utc))


class FakeProvider:
    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def generate(self, provider, credential, count, country, session_type):
        with self._lock:
            self.calls += 1
        return [GeneratedProxy("global.711proxy.com", 20000, "u", "GEN-SECRET") for _ in range(count)]


class FakeTester:
    def __init__(self, exc=None):
        self._exc = exc

    def run_fast(self, url, timeout_seconds=5):
        if self._exc:
            raise self._exc
        return _ok()


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


def _mark_all_login(ctx):
    with ctx.session_factory() as session:
        for eid in ctx.email_ids:
            service.finalize_email(session, session.get(ShopCheckEmail, eid), "login_success")


def _store():
    store = MemoryCredentialStore()
    store.put("proxy-provider:seveneleven", ProxyCredential("acct", "ACCT-SECRET"))
    return store


def _make_run(db_session_factory, store, text, per=5, max_parallel=3):
    with db_session_factory() as session:
        payload = ShopCheckRunCreate(
            email_text=text, emails_per_profile=per, max_parallel=max_parallel,
            authorized_only_ack=True,
        )
        return service.create_run(session, store, payload, db_session_factory)["run"]["id"]


def _emails(n):
    return "\n".join(f"u{i}@example.com" for i in range(n))


def _wait(db_session_factory, run_id, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with db_session_factory() as session:
            detail = service.get_run_detail(session, run_id)
        if detail["status"] in _TERMINAL:
            return detail
        time.sleep(0.02)
    return detail


def test_start_claims_once_and_completes(db_session_factory):
    store = _store()
    coord = ShopCheckCoordinator(db_session_factory, store, FakeProvider(), FakeTester(),
                                 FakeLauncher(), process_worker=_mark_all_login)
    run_id = _make_run(db_session_factory, store, _emails(12), per=5)  # 3 workers
    try:
        with db_session_factory() as session:
            coord.start(session, run_id)
        detail = _wait(db_session_factory, run_id)
        assert detail["status"] == "completed"
        assert detail["worker_count"] == 3
        assert detail["terminal_count"] == 12
    finally:
        coord.shutdown()


def test_duplicate_start_is_noop(db_session_factory):
    store = _store()
    coord = ShopCheckCoordinator(db_session_factory, store, FakeProvider(), FakeTester(),
                                 FakeLauncher(), process_worker=_mark_all_login)
    run_id = _make_run(db_session_factory, store, _emails(5))
    try:
        with db_session_factory() as session:
            coord.start(session, run_id)
        with db_session_factory() as session:
            coord.start(session, run_id)  # second start
        _wait(db_session_factory, run_id)
        with db_session_factory() as session:
            workers = session.query(ShopCheckWorker).filter_by(run_id=run_id).count()
        assert workers == 1  # no duplicate workers from the second start
    finally:
        coord.shutdown()


def test_max_parallel_is_honored(db_session_factory):
    store = _store()
    active = {"now": 0, "max": 0}
    lock = threading.Lock()

    def slow(ctx):
        with lock:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        time.sleep(0.05)
        with lock:
            active["now"] -= 1
        _mark_all_login(ctx)

    coord = ShopCheckCoordinator(db_session_factory, store, FakeProvider(), FakeTester(),
                                 FakeLauncher(), process_worker=slow)
    run_id = _make_run(db_session_factory, store, _emails(25), per=5, max_parallel=2)  # 5 workers
    try:
        with db_session_factory() as session:
            coord.start(session, run_id)
        _wait(db_session_factory, run_id)
        assert active["max"] <= 2
    finally:
        coord.shutdown()


def test_proxy_failure_marks_emails_proxy_failed(db_session_factory):
    store = _store()
    coord = ShopCheckCoordinator(
        db_session_factory, store, FakeProvider(), FakeTester(ProxyTestFailure("dns_failed")),
        FakeLauncher(), process_worker=_mark_all_login,
    )
    run_id = _make_run(db_session_factory, store, _emails(5))
    try:
        with db_session_factory() as session:
            coord.start(session, run_id)
        detail = _wait(db_session_factory, run_id)
        assert detail["status"] == "completed_with_issues"
        assert detail["result_counts"].get("proxy_failed") == 5
        assert detail["retryable_count"] == 5
    finally:
        coord.shutdown()


def test_cancel_marks_remaining_emails_cancelled(db_session_factory):
    store = _store()

    def slow(ctx):
        time.sleep(0.2)
        _mark_all_login(ctx)

    coord = ShopCheckCoordinator(db_session_factory, store, FakeProvider(), FakeTester(),
                                 FakeLauncher(), process_worker=slow)
    run_id = _make_run(db_session_factory, store, _emails(10), per=5, max_parallel=1)
    try:
        with db_session_factory() as session:
            coord.start(session, run_id)
        time.sleep(0.05)
        with db_session_factory() as session:
            coord.cancel(session, run_id)
        detail = _wait(db_session_factory, run_id)
        assert detail["status"] == "cancelled"
        # every email is terminal (cancelled or processed); none left pending
        with db_session_factory() as session:
            pending = session.query(ShopCheckEmail).filter_by(run_id=run_id).filter(
                ShopCheckEmail.state != "terminal"
            ).count()
        assert pending == 0
    finally:
        coord.shutdown()


def test_no_secret_leaks_end_to_end(db_session_factory):
    store = _store()
    sentinel_email = "sentinel.person@corp-example.com"
    coord = ShopCheckCoordinator(
        db_session_factory, store, FakeProvider(), FakeTester(ProxyTestFailure("timeout")),
        FakeLauncher(), process_worker=_mark_all_login,
    )
    run_id = _make_run(db_session_factory, store, sentinel_email)
    try:
        with db_session_factory() as session:
            coord.start(session, run_id)
        _wait(db_session_factory, run_id)
        with db_session_factory() as session:
            detail = service.get_run_detail(session, run_id)
            page = service.list_emails(session, run_id, page=1, page_size=50, result=None)
            worker_errors = [w["error"] for w in detail["workers"]]
        blob = str(detail) + str(page)
        assert sentinel_email not in blob
        assert "ACCT-SECRET" not in blob and "GEN-SECRET" not in blob
        assert all("ACCT-SECRET" not in (e or "") for e in worker_errors)
    finally:
        coord.shutdown()


from manager_backend.features.shop_check import provisioner as _prov  # noqa: E402


def _interrupted(db_session_factory, store, n, per=5):
    run_id = _make_run(db_session_factory, store, _emails(n), per=per)
    with db_session_factory() as session:
        _prov.group_workers(session, run_id)
        run = service.require_run(session, run_id)
        run.status = "running"
        run.started_at = datetime(2026, 7, 29, tzinfo=timezone.utc)
        session.commit()
    return run_id


def test_recover_resumes_interrupted_run(db_session_factory):
    store = _store()
    coord = ShopCheckCoordinator(db_session_factory, store, FakeProvider(), FakeTester(),
                                 FakeLauncher(), process_worker=_mark_all_login)
    run_id = _interrupted(db_session_factory, store, 10, per=5)  # 2 workers, pending
    try:
        assert coord.recover(db_session_factory) == 2
        detail = _wait(db_session_factory, run_id)
        assert detail["status"] == "completed"
        assert detail["terminal_count"] == 10
    finally:
        coord.shutdown()


def test_recover_reuses_existing_proxy_and_profile(db_session_factory):
    store = _store()
    provider = FakeProvider()
    launcher = FakeLauncher()
    coord = ShopCheckCoordinator(db_session_factory, store, provider, FakeTester(),
                                 launcher, process_worker=_mark_all_login)
    run_id = _interrupted(db_session_factory, store, 5, per=5)  # 1 worker
    # Simulate a crash AFTER provisioning: worker already owns proxy + profile.
    with db_session_factory() as session:
        worker = session.query(ShopCheckWorker).filter_by(run_id=run_id).one()
        worker.profile_id = "already-owned-profile"
        worker.proxy_id = "already-owned-proxy"
        session.commit()
    try:
        coord.recover(db_session_factory)
        detail = _wait(db_session_factory, run_id)
        assert detail["status"] == "completed"
        assert provider.calls == 0  # no new proxy generated
        assert "already-owned-profile" in launcher.started  # resumed at launch
    finally:
        coord.shutdown()


def test_recover_twice_does_not_double_process(db_session_factory):
    store = _store()
    counts: dict[str, int] = {}
    lock = threading.Lock()

    def counting(ctx):
        with lock:
            counts[ctx.worker_id] = counts.get(ctx.worker_id, 0) + 1
        time.sleep(0.05)
        _mark_all_login(ctx)

    coord = ShopCheckCoordinator(db_session_factory, store, FakeProvider(), FakeTester(),
                                 FakeLauncher(), process_worker=counting)
    run_id = _interrupted(db_session_factory, store, 10, per=5)
    try:
        coord.recover(db_session_factory)
        coord.recover(db_session_factory)  # second, racing pass
        _wait(db_session_factory, run_id)
        assert counts and all(c == 1 for c in counts.values())  # each worker once
    finally:
        coord.shutdown()


def test_many_workers_commit_without_sqlite_lock_errors(db_session_factory):
    store = _store()
    coord = ShopCheckCoordinator(db_session_factory, store, FakeProvider(), FakeTester(),
                                 FakeLauncher(), process_worker=_mark_all_login)
    run_id = _make_run(db_session_factory, store, _emails(50), per=5, max_parallel=5)  # 10 workers
    try:
        with db_session_factory() as session:
            coord.start(session, run_id)
        detail = _wait(db_session_factory, run_id, timeout=20)
        assert detail["status"] == "completed"
        assert detail["terminal_count"] == 50
        assert detail["error"] is None  # no 'database is locked' surfaced
    finally:
        coord.shutdown()
