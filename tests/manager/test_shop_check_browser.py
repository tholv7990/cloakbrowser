"""Per-email Shop flow + the coordinator's injected process_worker.

All browser I/O goes through the ShopSession protocol; tests drive a fake, so
there is no browser or network here. The real CdpShopSession is validated by the
authenticated Windows smoke test, not unit tests.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select

from manager_backend.features.proxies.credentials import (
    MemoryCredentialStore,
    ProxyCredential,
)
from manager_backend.features.proxies.providers import GeneratedProxy
from manager_backend.features.proxies.testing import QuickTestResult
from manager_backend.features.shop_check import service
from manager_backend.features.shop_check.browser import (
    EmailOutcome,
    check_email,
    make_process_worker,
)
from manager_backend.features.shop_check.coordinator import (
    ShopCheckCoordinator,
    WorkerContext,
)
from manager_backend.features.shop_check.schemas import ShopCheckRunCreate
from manager_backend.models import ShopCheckEmail, ShopCheckWorker

_PHONE_OTP_HTML = (
    "<h1>Enter your code</h1>"
    "<p>We texted a code to the phone number ending in 34.</p>"
)
_ACCOUNT_NOT_FOUND_HTML = "<p>We couldn't find an account with that email address.</p>"
_LOGIN_OK_HTML = "<a href='/logout'>Log out</a><p>You're signed in.</p>"


class FakeShopSession:
    """Scripts a page response per email; records the driven actions."""

    def __init__(self, by_email: dict[str, str], phone_hint: str | None = None):
        self._by_email = by_email
        self._phone_hint = phone_hint
        self._current = ""
        self.filled: list[str] = []
        self.cleared = 0
        self.closed = False
        self.visited: list[str] = []

    def goto(self, url):
        self.visited.append(url)

    def fill_email(self, email):
        self._current = email
        self.filled.append(email)

    def submit(self):
        pass

    def page_html(self):
        return self._by_email.get(self._current, "<p>loading…</p>")

    def phone_hint(self):
        return self._phone_hint

    def clear_origin_state(self):
        self.cleared += 1

    def screenshot(self):
        return None

    def close(self):
        self.closed = True


# --- per-email flow ---------------------------------------------------------
def test_check_email_classifies_and_navigates():
    session = FakeShopSession({"a@x.com": _ACCOUNT_NOT_FOUND_HTML})
    outcome = check_email(session, "a@x.com", target_url="https://shop.app/")
    assert outcome.result == "account_not_found"
    assert outcome.phone is None
    assert session.visited == ["https://shop.app/"]
    assert session.filled == ["a@x.com"]


def test_check_email_parses_phone_on_phone_otp():
    session = FakeShopSession({"a@x.com": _PHONE_OTP_HTML}, phone_hint="+84 ••• ••34")
    outcome = check_email(session, "a@x.com", target_url="https://shop.app/")
    assert outcome.result == "phone_otp_required"
    assert outcome.phone is not None
    assert outcome.phone.country_code == "VN"
    assert outcome.phone.suffix == "34"


def test_phone_hint_only_read_for_phone_otp():
    session = FakeShopSession({"a@x.com": _LOGIN_OK_HTML}, phone_hint="+1 ••34")
    outcome = check_email(session, "a@x.com", target_url="https://shop.app/")
    assert outcome.result == "login_success"
    assert outcome.phone is None  # not consulted when the page isn't a phone OTP


# --- process_worker over a real DB ------------------------------------------
def _store():
    store = MemoryCredentialStore()
    store.put("proxy-provider:seveneleven", ProxyCredential("acct", "ACCT-SECRET"))
    return store


def _seed_worker(db_session_factory, store, emails: dict[str, str]):
    """Persist a run + one worker owning the given {email: expected_result} set."""
    text = "\n".join(emails)
    with db_session_factory() as session:
        payload = ShopCheckRunCreate(
            email_text=text, emails_per_profile=5, max_parallel=1, authorized_only_ack=True
        )
        run_id = service.create_run(session, store, payload, db_session_factory)["run"]["id"]
        from manager_backend.features.shop_check.provisioner import group_workers

        group_workers(session, run_id)
        worker = session.query(ShopCheckWorker).filter_by(run_id=run_id).one()
        worker.profile_id = "profile-1"
        session.commit()
        email_ids = [
            e.id
            for e in session.scalars(
                select(ShopCheckEmail)
                .where(ShopCheckEmail.worker_id == worker.id)
                .order_by(ShopCheckEmail.ordinal)
            )
        ]
        return run_id, worker.id, email_ids


def _ctx(db_session_factory, store, run_id, worker_id, email_ids, is_cancelled=lambda: False):
    return WorkerContext(
        run_id=run_id,
        worker_id=worker_id,
        profile_id="profile-1",
        email_ids=email_ids,
        session_factory=db_session_factory,
        store=store,
        is_cancelled=is_cancelled,
    )


def test_process_worker_finalizes_each_email_and_clears_between(db_session_factory):
    store = _store()
    emails = {"one@x.com": _ACCOUNT_NOT_FOUND_HTML, "two@x.com": _LOGIN_OK_HTML}
    run_id, worker_id, email_ids = _seed_worker(db_session_factory, store, emails)

    session = FakeShopSession(emails)
    process_worker = make_process_worker(lambda ctx: session)
    process_worker(_ctx(db_session_factory, store, run_id, worker_id, email_ids))

    with db_session_factory() as db:
        rows = db.query(ShopCheckEmail).filter_by(run_id=run_id).order_by(ShopCheckEmail.ordinal).all()
        results = {r.email_masked: r.result for r in rows}
        assert all(r.state == "terminal" for r in rows)
    # two emails processed, origin state cleared after each, session closed
    assert set(results.values()) == {"account_not_found", "login_success"}
    assert session.cleared == 2
    assert session.closed is True


def test_process_worker_stops_on_cancel_leaving_rest_pending(db_session_factory):
    store = _store()
    emails = {f"u{i}@x.com": _ACCOUNT_NOT_FOUND_HTML for i in range(3)}
    run_id, worker_id, email_ids = _seed_worker(db_session_factory, store, emails)

    calls = {"n": 0}

    def cancel_after_first():
        return calls["n"] >= 1

    session = FakeShopSession(emails)
    original = session.fill_email

    def counting(email):
        calls["n"] += 1
        original(email)

    session.fill_email = counting
    process_worker = make_process_worker(lambda ctx: session)
    process_worker(_ctx(db_session_factory, store, run_id, worker_id, email_ids, cancel_after_first))

    with db_session_factory() as db:
        rows = db.query(ShopCheckEmail).filter_by(run_id=run_id).all()
        terminal = [r for r in rows if r.state == "terminal"]
        pending = [r for r in rows if r.state == "pending"]
    assert len(terminal) == 1  # only the first was processed before cancel
    assert len(pending) == 2   # coordinator marks these cancelled afterwards
    assert session.closed is True


def test_navigation_failure_is_a_navigation_failed_result(db_session_factory):
    store = _store()
    emails = {"boom@x.com": _ACCOUNT_NOT_FOUND_HTML}
    run_id, worker_id, email_ids = _seed_worker(db_session_factory, store, emails)

    class Exploding(FakeShopSession):
        def goto(self, url):
            raise RuntimeError("net::ERR_TIMED_OUT")

    session = Exploding(emails)
    make_process_worker(lambda ctx: session)(_ctx(db_session_factory, store, run_id, worker_id, email_ids))

    with db_session_factory() as db:
        row = db.query(ShopCheckEmail).filter_by(run_id=run_id).one()
        assert row.result == "navigation_failed"
        assert row.state == "terminal"


def test_full_email_never_lands_in_the_row(db_session_factory):
    store = _store()
    sentinel = "sentinel.person@corp-example.com"
    emails = {sentinel: _ACCOUNT_NOT_FOUND_HTML}
    run_id, worker_id, email_ids = _seed_worker(db_session_factory, store, emails)

    session = FakeShopSession(emails)
    make_process_worker(lambda ctx: session)(_ctx(db_session_factory, store, run_id, worker_id, email_ids))
    assert session.filled == [sentinel]  # the real address WAS used to drive the page

    with db_session_factory() as db:
        row = db.query(ShopCheckEmail).filter_by(run_id=run_id).one()
        for value in (row.email_masked, row.result, row.error):
            assert sentinel not in (value or "")


# --- coordinator injects it end to end --------------------------------------
class _Provider:
    def generate(self, provider, credential, count, country, session_type):
        return [GeneratedProxy("global.711proxy.com", 20000, "u", "SECRET") for _ in range(count)]


class _Tester:
    def run_fast(self, url, timeout_seconds=5):
        return QuickTestResult("203.0.113.5", True, 100, datetime(2026, 7, 29, tzinfo=timezone.utc))


class _Launcher:
    def start_and_wait_ready(self, profile_id, *, timeout_seconds, is_cancelled):
        return f"http://127.0.0.1/{profile_id}"

    def stop(self, profile_id):
        pass


def test_coordinator_runs_with_the_real_process_worker(db_session_factory):
    store = _store()
    html_by_email = {f"u{i}@example.com": _ACCOUNT_NOT_FOUND_HTML for i in range(5)}
    process_worker = make_process_worker(lambda ctx: FakeShopSession(html_by_email))
    coord = ShopCheckCoordinator(
        db_session_factory, store, _Provider(), _Tester(), _Launcher(),
        process_worker=process_worker,
    )
    with db_session_factory() as session:
        payload = ShopCheckRunCreate(
            email_text="\n".join(html_by_email), emails_per_profile=5,
            max_parallel=1, authorized_only_ack=True,
        )
        run_id = service.create_run(session, store, payload, db_session_factory)["run"]["id"]
    try:
        with db_session_factory() as session:
            coord.start(session, run_id)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with db_session_factory() as session:
                detail = service.get_run_detail(session, run_id)
            if detail["status"] in {"completed", "completed_with_issues"}:
                break
            time.sleep(0.02)
        assert detail["status"] == "completed"  # account_not_found is definitive, not retryable
        assert detail["result_counts"].get("account_not_found") == 5
    finally:
        coord.shutdown()
