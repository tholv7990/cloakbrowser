"""Shop-check provisioning: worker allocation, per-profile 711 proxy, profile
creation, and durable ownership.

No threads and no browser-page automation here — the coordinator drives these
functions on its worker threads. Everything is idempotent so a restart never
creates a duplicate worker, proxy, or profile.
"""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import ShopCheckEmail, ShopCheckWorker
from .service import recompute_run, require_run


def group_workers(session: Session, run_id: str) -> int:
    """Divide the run's emails (in input/ordinal order) into groups of at most
    emails_per_profile and create exactly one worker per group. Idempotent: a
    worker ordinal already present is reused, and an email already assigned keeps
    its worker. Returns the number of worker groups.
    """
    run = require_run(session, run_id)
    per = run.emails_per_profile
    emails = list(
        session.scalars(
            select(ShopCheckEmail)
            .where(ShopCheckEmail.run_id == run_id)
            .order_by(ShopCheckEmail.ordinal, ShopCheckEmail.id)
        )
    )
    existing = {
        worker.ordinal: worker
        for worker in session.scalars(
            select(ShopCheckWorker).where(ShopCheckWorker.run_id == run_id)
        )
    }
    group_count = math.ceil(len(emails) / per) if emails else 0
    for ordinal in range(group_count):
        group = emails[ordinal * per : (ordinal + 1) * per]
        worker = existing.get(ordinal)
        if worker is None:
            worker = ShopCheckWorker(
                run_id=run_id,
                ordinal=ordinal,
                state="pending",
                assigned_count=len(group),
            )
            session.add(worker)
            session.flush()
            existing[ordinal] = worker
        for email in group:
            if email.worker_id is None:
                email.worker_id = worker.id
    session.commit()
    # worker_count is recomputed from committed worker rows, never guessed.
    recompute_run(session, run_id)
    return group_count
