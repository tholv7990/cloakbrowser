"""Durable recovery for partially provisioned Shop-check credentials.

A credential is written to CredentialStore before the email row is committed. A
journal row (committed first) records the ref so an orphan secret can be cleaned
even if the DB rollback AND the immediate compensation both fail. Startup
reconciliation removes only journal refs NOT referenced by a committed email row,
never a referenced secret, and is idempotent.
"""

from __future__ import annotations

import pytest
from keyring.errors import KeyringError, PasswordDeleteError

from manager_backend.errors import ManagerError
from manager_backend.features.proxies.credentials import (
    KeyringCredentialStore,
    MemoryCredentialStore,
    ProxyCredential,
)
from manager_backend.features.shop_check import service
from manager_backend.features.shop_check.schemas import ShopCheckRunCreate
from manager_backend.models import (
    ShopCheckCredentialJournal,
    ShopCheckEmail,
    ShopCheckRun,
)


class _FakeWindowsKeyring:
    """delete_password raises PasswordDeleteError for a missing entry, like the
    real Windows backend — the exact behavior that broke naive reconciliation."""

    def __init__(self):
        self._data: dict[tuple[str, str], str] = {}

    def set_password(self, service_name, ref, payload):
        self._data[(service_name, ref)] = payload

    def get_password(self, service_name, ref):
        return self._data.get((service_name, ref))

    def delete_password(self, service_name, ref):
        if (service_name, ref) not in self._data:
            raise PasswordDeleteError("missing")
        del self._data[(service_name, ref)]


def _payload(text: str) -> ShopCheckRunCreate:
    return ShopCheckRunCreate(
        email_text=text, emails_per_profile=5, max_parallel=3, authorized_only_ack=True
    )


class _PutFails(MemoryCredentialStore):
    def __init__(self, fail_on: int):
        super().__init__()
        self._fail_on = fail_on
        self._puts = 0

    def put(self, reference, credential):
        self._puts += 1
        if self._puts == self._fail_on:
            raise RuntimeError("store put failed")
        super().put(reference, credential)


class _DeleteFails(MemoryCredentialStore):
    def delete(self, reference):
        raise RuntimeError("store delete failed")


def test_store_put_failure_rolls_back_and_cleans_written_refs(db_session_factory):
    store = _PutFails(fail_on=2)
    with db_session_factory() as session:
        with pytest.raises(RuntimeError):
            service.create_run(session, store, _payload("a@x.co\nb@x.co\nc@x.co"), db_session_factory)
    with db_session_factory() as session:
        assert session.query(ShopCheckRun).count() == 0
        assert session.query(ShopCheckEmail).count() == 0
    assert store._values == {}  # the one successful put was compensated
    # The journal retained the durable record for the startup backstop.
    with db_session_factory() as session:
        assert session.query(ShopCheckCredentialJournal).count() >= 1


def test_commit_failure_after_puts_is_compensated(db_session_factory, monkeypatch):
    store = MemoryCredentialStore()
    with db_session_factory() as session:
        original_commit = session.commit
        calls = {"n": 0}

        def failing_commit():
            calls["n"] += 1
            raise RuntimeError("db commit failed")

        # Fail only the main-transaction commit inside create_run.
        monkeypatch.setattr(session, "commit", failing_commit)
        with pytest.raises(RuntimeError):
            service.create_run(session, store, _payload("a@x.co\nb@x.co"), db_session_factory)
        monkeypatch.setattr(session, "commit", original_commit)
    assert store._values == {}  # puts compensated after the commit failed


def test_reconciliation_removes_orphans_when_compensation_failed(db_session_factory, monkeypatch):
    # puts succeed, the commit fails, AND compensation delete fails -> the secrets
    # are orphaned in the store and only the journal + reconciliation can clean them.
    store = _DeleteFails()
    with db_session_factory() as session:
        monkeypatch.setattr(session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit")))
        with pytest.raises(RuntimeError):
            service.create_run(session, store, _payload("a@x.co\nb@x.co"), db_session_factory)

    assert len(store._values) >= 1  # orphans stranded in the store
    with db_session_factory() as session:
        assert session.query(ShopCheckCredentialJournal).count() >= 1

    # A working store lets reconciliation clean the orphans (same refs).
    working = MemoryCredentialStore()
    working._values = dict(store._values)
    removed = service.reconcile_orphan_credentials(db_session_factory, working)
    assert removed >= 1
    assert working._values == {}
    with db_session_factory() as session:
        assert session.query(ShopCheckCredentialJournal).count() == 0

    # Idempotent: a second pass removes nothing and does not error.
    assert service.reconcile_orphan_credentials(db_session_factory, working) == 0


def test_reconciliation_never_deletes_a_referenced_credential(db_session_factory):
    store = MemoryCredentialStore()
    with db_session_factory() as session:
        result = service.create_run(session, store, _payload("keep@x.co"), db_session_factory)
    run_id = result["run"]["id"]
    with db_session_factory() as session:
        ref = session.query(ShopCheckEmail).filter_by(run_id=run_id).one().credential_ref
    assert store.get(ref) is not None

    # Even if a stale journal row exists for that referenced ref, reconciliation
    # must not delete the live secret.
    with db_session_factory() as session:
        session.add(ShopCheckCredentialJournal(ref=ref, run_id=run_id))
        session.commit()
    service.reconcile_orphan_credentials(db_session_factory, store)
    assert store.get(ref) is not None  # referenced secret preserved
    with db_session_factory() as session:
        assert session.query(ShopCheckCredentialJournal).count() == 0  # served journal cleared


def test_reconciliation_with_real_keyring_semantics(db_session_factory):
    # Crash after journal commit: two refs journalled, only one secret written
    # (as if the process died mid-provisioning). A never-written ref makes the
    # keyring raise PasswordDeleteError, which must count as cleaned, not stuck.
    backend = _FakeWindowsKeyring()
    store = KeyringCredentialStore(keyring_backend=backend)
    with db_session_factory() as session:
        session.add(ShopCheckCredentialJournal(ref="ref-present", run_id="run-x"))
        session.add(ShopCheckCredentialJournal(ref="ref-never", run_id="run-x"))
        session.commit()
    store.put("ref-present", ProxyCredential("a@b.co", ""))

    removed = service.reconcile_orphan_credentials(db_session_factory, store)
    assert removed == 2  # one deleted, one already-absent — both journal rows cleared
    assert store.get("ref-present") is None
    with db_session_factory() as session:
        assert session.query(ShopCheckCredentialJournal).count() == 0
    # idempotent second pass
    assert service.reconcile_orphan_credentials(db_session_factory, store) == 0


def test_reconciliation_keeps_journal_when_store_genuinely_unavailable(db_session_factory):
    class _Unavailable:
        def delete(self, ref):
            raise ManagerError("credential_store_unavailable", "down", 503)

    with db_session_factory() as session:
        session.add(ShopCheckCredentialJournal(ref="ref-1", run_id="run-y"))
        session.commit()
    removed = service.reconcile_orphan_credentials(db_session_factory, _Unavailable())
    assert removed == 0
    with db_session_factory() as session:
        # journal retained for the next startup; never dropped on a genuine failure
        assert session.query(ShopCheckCredentialJournal).count() == 1


def test_reconciliation_never_deletes_referenced_credential_keyring(db_session_factory):
    backend = _FakeWindowsKeyring()
    store = KeyringCredentialStore(keyring_backend=backend)
    with db_session_factory() as session:
        run = ShopCheckRun(
            status="queued", emails_per_profile=5, max_parallel=3,
            target_url="https://shop.app/", total_emails=1,
        )
        session.add(run)
        session.flush()
        session.add(
            ShopCheckEmail(
                run_id=run.id, ordinal=0, email_fingerprint="f" * 64,
                credential_ref="ref-live", email_masked="a***@b***.com", state="pending",
            )
        )
        session.add(ShopCheckCredentialJournal(ref="ref-live", run_id=run.id))
        session.commit()
    store.put("ref-live", ProxyCredential("keep@b.co", ""))

    service.reconcile_orphan_credentials(db_session_factory, store)
    assert store.get("ref-live") is not None  # referenced secret preserved
    with db_session_factory() as session:
        assert session.query(ShopCheckCredentialJournal).count() == 0


def test_successful_run_clears_its_journal_rows(db_session_factory):
    store = MemoryCredentialStore()
    with db_session_factory() as session:
        service.create_run(session, store, _payload("a@x.co\nb@x.co"), db_session_factory)
    with db_session_factory() as session:
        # On success the journal rows have served their purpose and are removed.
        assert session.query(ShopCheckCredentialJournal).count() == 0
        assert session.query(ShopCheckEmail).count() == 2


def test_post_success_journal_cleanup_failure_still_returns_created_run(db_session_factory):
    # The run + emails commit; only the best-effort served-journal cleanup fails.
    # That must NOT turn a durable creation into a 500 (which would invite a
    # duplicate-run retry). The response is the created run; the journal rows are
    # left for startup reconciliation, which clears them without touching the
    # referenced secrets.
    store = MemoryCredentialStore()
    calls = {"n": 0}

    def flaky_factory():
        calls["n"] += 1
        session = db_session_factory()
        if calls["n"] == 2:  # the post-success cleanup transaction
            session.commit = lambda: (_ for _ in ()).throw(RuntimeError("cleanup commit"))
        return session

    with db_session_factory() as main:
        result = service.create_run(main, store, _payload("a@x.co\nb@x.co"), flaky_factory)

    run_id = result["run"]["id"]
    with db_session_factory() as session:
        assert session.query(ShopCheckRun).filter_by(id=run_id).count() == 1
        assert session.query(ShopCheckEmail).filter_by(run_id=run_id).count() == 2
        assert session.query(ShopCheckCredentialJournal).filter_by(run_id=run_id).count() == 2
    assert len(store._values) == 2  # secrets intact

    # Reconciliation clears the served journal rows without deleting referenced creds.
    service.reconcile_orphan_credentials(db_session_factory, store)
    with db_session_factory() as session:
        assert session.query(ShopCheckCredentialJournal).filter_by(run_id=run_id).count() == 0
    assert len(store._values) == 2
