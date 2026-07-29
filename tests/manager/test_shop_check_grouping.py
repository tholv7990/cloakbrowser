from __future__ import annotations

import pytest

from manager_backend.features.proxies.credentials import MemoryCredentialStore
from manager_backend.features.shop_check import provisioner, service
from manager_backend.features.shop_check.schemas import ShopCheckRunCreate
from manager_backend.models import ShopCheckEmail, ShopCheckWorker


def _make_run(db_session_factory, count: int, per: int) -> str:
    store = MemoryCredentialStore()
    emails = "\n".join(f"user{i}@example.com" for i in range(count)) or "placeholder@x.co"
    with db_session_factory() as session:
        payload = ShopCheckRunCreate(
            email_text=emails, emails_per_profile=per, max_parallel=3, authorized_only_ack=True
        )
        run_id = service.create_run(session, store, payload, db_session_factory)["run"]["id"]
    if count == 0:
        # remove the placeholder so the run genuinely has zero emails
        with db_session_factory() as session:
            session.query(ShopCheckEmail).filter_by(run_id=run_id).delete()
            session.commit()
    return run_id


@pytest.mark.parametrize(
    "count, per, expected_workers",
    [
        (0, 5, 0),
        (1, 5, 1),
        (5, 5, 1),
        (6, 5, 2),
        (999, 5, 200),
        (1000, 5, 200),
        (11, 3, 4),
    ],
)
def test_group_workers_counts_and_assignment(db_session_factory, count, per, expected_workers):
    run_id = _make_run(db_session_factory, count, per)
    with db_session_factory() as session:
        n = provisioner.group_workers(session, run_id)
    assert n == expected_workers

    with db_session_factory() as session:
        workers = session.query(ShopCheckWorker).filter_by(run_id=run_id).order_by(
            ShopCheckWorker.ordinal
        ).all()
        assert [w.ordinal for w in workers] == list(range(expected_workers))
        assert sum(w.assigned_count for w in workers) == count
        emails = session.query(ShopCheckEmail).filter_by(run_id=run_id).all()
        # every email is assigned to exactly one existing worker
        worker_ids = {w.id for w in workers}
        assert all(e.worker_id in worker_ids for e in emails)
        # worker_count recomputed from committed rows
        run = service.require_run(session, run_id)
        assert run.worker_count == expected_workers


def test_group_workers_is_idempotent(db_session_factory):
    run_id = _make_run(db_session_factory, 6, 5)
    with db_session_factory() as session:
        provisioner.group_workers(session, run_id)
    with db_session_factory() as session:
        provisioner.group_workers(session, run_id)  # second pass
    with db_session_factory() as session:
        workers = session.query(ShopCheckWorker).filter_by(run_id=run_id).all()
        assert len(workers) == 2  # no duplicates
        assert [w.ordinal for w in sorted(workers, key=lambda w: w.ordinal)] == [0, 1]


def test_group_workers_contiguous_ordinal_ranges(db_session_factory):
    run_id = _make_run(db_session_factory, 7, 3)  # groups: [0,1,2],[3,4,5],[6]
    with db_session_factory() as session:
        provisioner.group_workers(session, run_id)
    with db_session_factory() as session:
        workers = {
            w.ordinal: w.id
            for w in session.query(ShopCheckWorker).filter_by(run_id=run_id)
        }
        emails = session.query(ShopCheckEmail).filter_by(run_id=run_id).order_by(
            ShopCheckEmail.ordinal
        ).all()
        assigned = [(e.ordinal, e.worker_id) for e in emails]
        assert assigned == [
            (0, workers[0]), (1, workers[0]), (2, workers[0]),
            (3, workers[1]), (4, workers[1]), (5, workers[1]),
            (6, workers[2]),
        ]
