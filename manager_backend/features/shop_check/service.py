"""Shop-check service: run persistence, read serialization, and cancellation.

Aggregate counts are always recomputed from the email rows, never incremented
optimistically, so retries and concurrent workers cannot double-count. Read
serialization deliberately omits the credential reference, the fingerprint, and
the full email — only a masked value plus visible result/phone metadata leave
this layer.
"""

from __future__ import annotations

import math
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...models import (
    ShopCheckEmail,
    ShopCheckRun,
    ShopCheckWorker,
    utc_now,
)
from .schemas import RETRYABLE_RESULTS

_TERMINAL_RUN_STATES = frozenset(
    {"completed", "completed_with_issues", "cancelled", "failed"}
)


def require_run(session: Session, run_id: str) -> ShopCheckRun:
    run = session.get(ShopCheckRun, run_id)
    if run is None:
        raise ManagerError("shop_check_run_not_found", "The requested run was not found.", 404)
    return run


def _result_counts(session: Session, run_id: str) -> dict[str, int]:
    rows = session.execute(
        select(ShopCheckEmail.result, func.count())
        .where(ShopCheckEmail.run_id == run_id, ShopCheckEmail.result.is_not(None))
        .group_by(ShopCheckEmail.result)
    ).all()
    return {result: int(count) for result, count in rows}


def _run_summary(session: Session, run: ShopCheckRun) -> dict:
    return {
        "id": run.id,
        "status": run.status,
        "region": run.region,
        "emails_per_profile": run.emails_per_profile,
        "max_parallel": run.max_parallel,
        "target_url": run.target_url,
        "total_emails": run.total_emails,
        "terminal_count": run.terminal_count,
        "retryable_count": run.retryable_count,
        "worker_count": run.worker_count,
        "cleanup_state": run.cleanup_state,
        "result_counts": _result_counts(session, run.id),
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def _worker_to_dict(worker: ShopCheckWorker) -> dict:
    return {
        "id": worker.id,
        "ordinal": worker.ordinal,
        "state": worker.state,
        "profile_id": worker.profile_id,
        "proxy_id": worker.proxy_id,
        "assigned_count": worker.assigned_count,
        "processed_count": worker.processed_count,
        "error": worker.error,
    }


def _email_to_dict(email: ShopCheckEmail) -> dict:
    return {
        "id": email.id,
        "ordinal": email.ordinal,
        "email_masked": email.email_masked,
        "state": email.state,
        "result": email.result,
        "retryable": email.result in RETRYABLE_RESULTS,
        "phone_prefix": email.phone_prefix,
        "phone_suffix": email.phone_suffix,
        "phone_country_code": email.phone_country_code,
        "phone_country_name": email.phone_country_name,
        "phone_region_name": email.phone_region_name,
        "phone_confidence": email.phone_confidence,
        "retry_count": email.retry_count,
        "worker_id": email.worker_id,
        "checked_at": email.checked_at,
    }


def run_detail(session: Session, run: ShopCheckRun) -> dict:
    workers = session.scalars(
        select(ShopCheckWorker)
        .where(ShopCheckWorker.run_id == run.id)
        .order_by(ShopCheckWorker.ordinal, ShopCheckWorker.id)
    ).all()
    detail = _run_summary(session, run)
    detail.update(
        {
            "profile_prefix": run.profile_prefix,
            "output_dir": run.output_dir,
            "error": run.error,
            "workers": [_worker_to_dict(w) for w in workers],
        }
    )
    return detail


def get_run_detail(session: Session, run_id: str) -> dict:
    return run_detail(session, require_run(session, run_id))


def list_runs(session: Session) -> list[dict]:
    runs = session.scalars(
        select(ShopCheckRun).order_by(ShopCheckRun.created_at.desc())
    ).all()
    return [_run_summary(session, run) for run in runs]


def list_emails(
    session: Session,
    run_id: str,
    *,
    page: int,
    page_size: int,
    result: str | None,
) -> dict:
    require_run(session, run_id)
    filters = [ShopCheckEmail.run_id == run_id]
    if result is not None:
        filters.append(ShopCheckEmail.result == result)
    total = int(
        session.scalar(select(func.count()).select_from(ShopCheckEmail).where(*filters)) or 0
    )
    rows = session.scalars(
        select(ShopCheckEmail)
        .where(*filters)
        .order_by(ShopCheckEmail.ordinal, ShopCheckEmail.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_email_to_dict(email) for email in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 0,
    }


def create_run(session: Session, store, payload) -> dict:
    """Persist a queued run from validated settings.

    NOTE: email parsing, CredentialStore writes, email-row creation, and worker
    grouping are wired in Task 3 (features/shop_check/input.py). This skeleton
    persists the run settings and returns the locked response contract with a
    zeroed input summary so the route/schema contract can be reviewed first.
    """
    run = ShopCheckRun(
        status="queued",
        region=payload.region,
        emails_per_profile=payload.emails_per_profile,
        max_parallel=payload.max_parallel,
        target_url="https://shop.app/",
        profile_prefix=payload.profile_prefix,
        output_dir=payload.output_dir,
        total_emails=0,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return {
        "run": run_detail(session, run),
        "input_summary": {
            "total_lines": 0,
            "valid": 0,
            "duplicates": 0,
            "invalid": 0,
            "worker_count": 0,
        },
    }


def recompute_run(session: Session, run_id: str) -> ShopCheckRun:
    """Recompute aggregate counters + terminal status from the email rows.

    Idempotent and safe under concurrency (the caller serializes writes). A run
    is finished only when every email is terminal; it is completed_with_issues
    when all are terminal but a retryable/issue result remains.
    """
    run = require_run(session, run_id)
    emails = session.scalars(
        select(ShopCheckEmail).where(ShopCheckEmail.run_id == run_id)
    ).all()
    run.total_emails = len(emails)
    run.terminal_count = sum(1 for e in emails if e.state == "terminal")
    run.retryable_count = sum(
        1 for e in emails if e.result in RETRYABLE_RESULTS
    )
    run.worker_count = int(
        session.scalar(
            select(func.count()).select_from(ShopCheckWorker).where(
                ShopCheckWorker.run_id == run_id
            )
        )
        or 0
    )
    if run.status == "cancelled":
        if run.finished_at is None:
            run.finished_at = utc_now()
    elif emails and all(e.state == "terminal" for e in emails):
        run.status = "completed_with_issues" if run.retryable_count else "completed"
        if run.finished_at is None:
            run.finished_at = utc_now()
    session.commit()
    session.refresh(run)
    return run


def cancel_run(session: Session, run_id: str) -> dict:
    """Stop scheduling and mark any non-terminal email cancelled.

    Task 8 extends this to also signal the live coordinator; the persisted state
    here is the source of truth either way.
    """
    run = require_run(session, run_id)
    if run.status in _TERMINAL_RUN_STATES and run.status != "cancelled":
        raise ManagerError(
            "shop_check_run_finished", "A finished run cannot be cancelled.", 409
        )
    run.status = "cancelled"
    emails = session.scalars(
        select(ShopCheckEmail).where(
            ShopCheckEmail.run_id == run_id, ShopCheckEmail.state != "terminal"
        )
    ).all()
    for email in emails:
        email.state = "terminal"
        email.result = "cancelled"
        email.checked_at = utc_now()
    session.commit()
    recompute_run(session, run_id)
    return get_run_detail(session, run_id)
