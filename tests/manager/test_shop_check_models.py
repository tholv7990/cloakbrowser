from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from manager_backend.models import ShopCheckEmail, ShopCheckRun, ShopCheckWorker


def _run(**overrides) -> ShopCheckRun:
    values = dict(
        status="queued",
        region=None,
        emails_per_profile=5,
        max_parallel=3,
        target_url="https://shop.app/",
        total_emails=0,
    )
    values.update(overrides)
    return ShopCheckRun(**values)


def test_run_persists_with_defaults(db_session_factory):
    with db_session_factory() as session:
        run = _run()
        session.add(run)
        session.commit()
        session.refresh(run)
        assert run.id
        assert run.status == "queued"
        assert run.cleanup_state == "none"
        assert run.created_at is not None


def test_run_rejects_unknown_status(db_session_factory):
    with db_session_factory() as session:
        session.add(_run(status="bogus"))
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize("value", [0, 6, -1])
def test_run_rejects_out_of_range_emails_per_profile(db_session_factory, value):
    with db_session_factory() as session:
        session.add(_run(emails_per_profile=value))
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize("value", [0, 6])
def test_run_rejects_out_of_range_max_parallel(db_session_factory, value):
    with db_session_factory() as session:
        session.add(_run(max_parallel=value))
        with pytest.raises(IntegrityError):
            session.commit()


def test_email_stores_reference_not_plaintext(db_session_factory):
    with db_session_factory() as session:
        run = _run()
        session.add(run)
        session.flush()
        email = ShopCheckEmail(
            run_id=run.id,
            ordinal=0,
            email_fingerprint="a" * 64,
            credential_ref="ref-1",
            email_masked="jo***@ex***.com",
            state="pending",
        )
        session.add(email)
        session.commit()

    # The table exposes references + fingerprints, never a plaintext email column.
    assert "email" not in ShopCheckEmail.__table__.columns
    assert "email_fingerprint" in ShopCheckEmail.__table__.columns
    assert "credential_ref" in ShopCheckEmail.__table__.columns


def test_email_rejects_unknown_result(db_session_factory):
    with db_session_factory() as session:
        run = _run()
        session.add(run)
        session.flush()
        session.add(
            ShopCheckEmail(
                run_id=run.id,
                ordinal=0,
                email_fingerprint="b" * 64,
                credential_ref="ref-2",
                email_masked="a***@b***.com",
                state="terminal",
                result="not_a_real_result",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_worker_records_immutable_ownership_pair(db_session_factory):
    with db_session_factory() as session:
        run = _run()
        session.add(run)
        session.flush()
        worker = ShopCheckWorker(
            run_id=run.id,
            ordinal=0,
            state="pending",
            profile_id="profile-abc",
            assigned_count=5,
        )
        session.add(worker)
        session.commit()
        session.refresh(worker)
        # Ownership is the (run_id, profile_id) pair — resolved server-side at cleanup.
        assert worker.run_id == run.id
        assert worker.profile_id == "profile-abc"


def test_deleting_run_cascades_to_emails_and_workers(db_session_factory):
    with db_session_factory() as session:
        session.execute(text("PRAGMA foreign_keys=ON"))
        run = _run()
        session.add(run)
        session.flush()
        session.add(
            ShopCheckEmail(
                run_id=run.id,
                ordinal=0,
                email_fingerprint="c" * 64,
                credential_ref="ref-3",
                email_masked="a***@b***.com",
                state="pending",
            )
        )
        session.add(ShopCheckWorker(run_id=run.id, ordinal=0, state="pending"))
        session.commit()
        run_id = run.id

    with db_session_factory() as session:
        session.execute(text("PRAGMA foreign_keys=ON"))
        session.delete(session.get(ShopCheckRun, run_id))
        session.commit()
        assert (
            session.query(ShopCheckEmail).filter_by(run_id=run_id).count() == 0
        )
        assert (
            session.query(ShopCheckWorker).filter_by(run_id=run_id).count() == 0
        )
