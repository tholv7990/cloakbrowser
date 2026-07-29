from __future__ import annotations

import hashlib

import pytest

from manager_backend.features.proxies.credentials import MemoryCredentialStore
from manager_backend.features.shop_check import input as shop_input
from manager_backend.features.shop_check import service


# --- pure parsing -----------------------------------------------------------
def test_canonical_form_lowercases_domain_but_preserves_local_part():
    # Canonical = <submitted local part>@<lowercased domain>.
    parsed = shop_input.parse_email_input("  Alice@Example.COM \n")
    assert [e.normalized for e in parsed.valid] == ["Alice@example.com"]
    assert parsed.total_lines == 1


def test_dedup_is_case_insensitive_on_domain_only():
    # Same local + domain-case-only difference => duplicate. Different local
    # case => two distinct accounts (never merged).
    text = "user@Example.com\nuser@example.com\nUser@example.com\n"
    parsed = shop_input.parse_email_input(text)
    assert [e.normalized for e in parsed.valid] == ["user@example.com", "User@example.com"]
    assert len(parsed.duplicates) == 1
    assert parsed.duplicates[0].line == 2


def test_blank_lines_are_ignored_not_counted():
    parsed = shop_input.parse_email_input("a@b.co\n\n   \nc@d.co\n")
    assert [e.normalized for e in parsed.valid] == ["a@b.co", "c@d.co"]
    assert parsed.total_lines == 2
    assert parsed.invalid == []


def test_malformed_lines_are_reported_with_masked_value_and_line_number():
    text = "good@example.com\nnot-an-email\n@nope.com\na..b@x.co\na b@x.co\nmissing@\n"
    parsed = shop_input.parse_email_input(text)
    assert [e.normalized for e in parsed.valid] == ["good@example.com"]
    invalid_lines = {i.line for i in parsed.invalid}
    assert invalid_lines == {2, 3, 4, 5, 6}
    assert all(i.reason == "malformed" for i in parsed.invalid)
    masked = {i.masked for i in parsed.invalid}
    assert "not-an-email" not in masked


def test_fingerprint_is_sha256_of_canonical():
    parsed = shop_input.parse_email_input("Person@Example.COM")
    expected = hashlib.sha256("Person@example.com".encode()).hexdigest()
    assert parsed.valid[0].fingerprint == expected


def test_mask_email_hides_local_and_domain_body():
    masked = shop_input.mask_email("jonathan@example.com")
    assert "jonathan" not in masked
    assert masked.endswith(".com")
    assert "@" in masked


def test_worker_count_is_ceiling_division():
    assert shop_input.worker_count(0, 5) == 0
    assert shop_input.worker_count(1, 5) == 1
    assert shop_input.worker_count(5, 5) == 1
    assert shop_input.worker_count(6, 5) == 2
    assert shop_input.worker_count(11, 3) == 4


# --- create_run integration -------------------------------------------------
def test_create_run_stores_full_email_in_credentialstore_only(db_session_factory):
    store = MemoryCredentialStore()
    with db_session_factory() as session:
        result = service.create_run(
            session, store, _payload("Alice@Example.com\nbob@example.com"), db_session_factory
        )
    assert result["input_summary"]["valid"] == 2
    assert result["input_summary"]["worker_count"] == 1
    # Full emails live in the store, keyed by the row's credential_ref; the DB
    # holds only fingerprints + masked values.
    with db_session_factory() as session:
        from manager_backend.models import ShopCheckEmail

        rows = session.query(ShopCheckEmail).all()
        assert len(rows) == 2
        stored = {store.get(r.credential_ref).username for r in rows}
        # Local part preserved, domain lowercased.
        assert stored == {"Alice@example.com", "bob@example.com"}
        for r in rows:
            assert "@" in r.email_masked
            assert store.get(r.credential_ref).username not in r.email_masked


def test_create_run_rolls_back_and_compensates_on_store_failure(db_session_factory):
    class FailingStore(MemoryCredentialStore):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def put(self, reference, credential):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("store exploded")
            super().put(reference, credential)

    store = FailingStore()
    with db_session_factory() as session:
        with pytest.raises(RuntimeError):
            service.create_run(
                session, store, _payload("a@b.co\nc@d.co\ne@f.co"), db_session_factory
            )

    # Nothing persisted, and the first credential write was compensated.
    with db_session_factory() as session:
        from manager_backend.models import ShopCheckEmail, ShopCheckRun

        assert session.query(ShopCheckRun).count() == 0
        assert session.query(ShopCheckEmail).count() == 0
    assert store._values == {}  # the one successful put was compensated (deleted)


def test_create_run_rejects_input_with_no_valid_emails(db_session_factory):
    from manager_backend.errors import ManagerError

    store = MemoryCredentialStore()
    with db_session_factory() as session:
        with pytest.raises(ManagerError) as excinfo:
            service.create_run(session, store, _payload("nope\n@bad\n"), db_session_factory)
    assert excinfo.value.code == "shop_check_no_valid_emails"


def _payload(email_text: str):
    from manager_backend.features.shop_check.schemas import ShopCheckRunCreate

    return ShopCheckRunCreate(
        email_text=email_text,
        emails_per_profile=5,
        max_parallel=3,
        authorized_only_ack=True,
    )
