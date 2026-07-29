"""Durable recovery for partially provisioned Shop-check credentials.

A credential is written to CredentialStore before the email row is committed. A
journal row (committed first) records the ref so an orphan secret can be cleaned
even if the DB rollback AND the immediate compensation both fail. Startup
reconciliation removes only journal refs NOT referenced by a committed email row,
never a referenced secret, and is idempotent.
"""

from __future__ import annotations

import pytest

from manager_backend.features.proxies.credentials import MemoryCredentialStore, ProxyCredential
from manager_backend.features.shop_check import service
from manager_backend.features.shop_check.schemas import ShopCheckRunCreate
from manager_backend.models import (
    ShopCheckCredentialJournal,
    ShopCheckEmail,
    ShopCheckRun,
)


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


def test_successful_run_clears_its_journal_rows(db_session_factory):
    store = MemoryCredentialStore()
    with db_session_factory() as session:
        service.create_run(session, store, _payload("a@x.co\nb@x.co"), db_session_factory)
    with db_session_factory() as session:
        # On success the journal rows have served their purpose and are removed.
        assert session.query(ShopCheckCredentialJournal).count() == 0
        assert session.query(ShopCheckEmail).count() == 2
