"""Shop-check service: run persistence, read serialization, and cancellation.

Aggregate counts are always recomputed from the email rows, never incremented
optimistically, so retries and concurrent workers cannot double-count. Read
serialization deliberately omits the credential reference, the fingerprint, and
the full email — only a masked value plus visible result/phone metadata leave
this layer.
"""

from __future__ import annotations

import logging
import math

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...features.proxies.credentials import CredentialStore, ProxyCredential
from ...models import (
    ShopCheckCredentialJournal,
    ShopCheckEmail,
    ShopCheckRun,
    ShopCheckWorker,
    new_id,
    utc_now,
)
from .input import parse_email_input, worker_count
from .sanitize import sanitize_error
from .schemas import MAX_PREVIEW, RETRYABLE_RESULTS

_logger = logging.getLogger(__name__)


# --- error persistence (the only sanctioned way to write an error field) -----
# Callers MUST route every persisted error through these helpers so a raw
# exception string (which may embed an email or proxy secret) never lands in a
# column. Read serialization sanitizes again as defense in depth.
def set_run_error(run: ShopCheckRun, message: object, *secrets: str | None) -> None:
    run.error = sanitize_error(message, *secrets)


def set_worker_error(worker: ShopCheckWorker, message: object, *secrets: str | None) -> None:
    worker.error = sanitize_error(message, *secrets)


def set_email_error(email: ShopCheckEmail, message: object, *secrets: str | None) -> None:
    email.error = sanitize_error(message, *secrets)


def _clean(value: str | None) -> str | None:
    return sanitize_error(value) if value else None

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
        "error": _clean(worker.error),
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
            "error": _clean(run.error),
            "workers": [_worker_to_dict(w) for w in workers],
        }
    )
    return detail


def get_run_detail(session: Session, run_id: str) -> dict:
    return run_detail(session, require_run(session, run_id))


def list_runs(session: Session, *, page: int, page_size: int) -> dict:
    total = int(
        session.scalar(select(func.count()).select_from(ShopCheckRun)) or 0
    )
    runs = session.scalars(
        select(ShopCheckRun)
        .order_by(ShopCheckRun.created_at.desc(), ShopCheckRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_run_summary(session, run) for run in runs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": math.ceil(total / page_size) if total else 0,
    }


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


def create_run(
    session: Session, store: CredentialStore, payload, session_factory
) -> dict:
    """Parse the pasted input, securely persist the valid emails, and queue a run.

    Durability (SQLite + an OS CredentialStore cannot be truly atomic together):
    each ref is journalled in a SEPARATE committed transaction BEFORE its secret
    is written, so a secret whose email row never commits — or whose immediate
    compensation fails — is still recoverable. The run + email rows commit as one
    transaction; on failure they roll back, the written secrets are compensated
    best-effort, and the journal (already committed) lets startup reconciliation
    finish the cleanup. On success the journal rows are dropped. The raw input is
    never logged.
    """
    parsed = parse_email_input(payload.email_text)
    if not parsed.valid:
        raise ManagerError(
            "shop_check_no_valid_emails",
            "No valid email addresses were found in the input.",
            400,
        )

    # Pre-allocate the run id + refs so the durable journal can be written before
    # the run/email transaction (which may roll back and lose those rows).
    run_id = new_id()
    plan = [(ordinal, pe, new_id()) for ordinal, pe in enumerate(parsed.valid)]
    with session_factory() as journal_session:
        for _, _, ref in plan:
            journal_session.add(ShopCheckCredentialJournal(ref=ref, run_id=run_id))
        journal_session.commit()

    try:
        run = ShopCheckRun(
            id=run_id,
            status="queued",
            region=payload.region,
            emails_per_profile=payload.emails_per_profile,
            max_parallel=payload.max_parallel,
            target_url="https://shop.app/",
            profile_prefix=payload.profile_prefix,
            # output_dir stays NULL until export lands behind a validated root.
            total_emails=len(parsed.valid),
        )
        session.add(run)
        session.flush()
        for ordinal, parsed_email, ref in plan:
            store.put(ref, ProxyCredential(username=parsed_email.normalized, password=""))
            session.add(
                ShopCheckEmail(
                    run_id=run_id,
                    worker_id=None,
                    ordinal=ordinal,
                    email_fingerprint=parsed_email.fingerprint,
                    credential_ref=ref,
                    email_masked=parsed_email.masked,
                    state="pending",
                )
            )
        session.commit()
    except Exception:
        session.rollback()
        for _, _, ref in plan:
            try:
                store.delete(ref)
            except Exception:
                pass  # journal + startup reconciliation are the durable backstop
        raise

    # Success: the run/email transaction committed, so the request has SUCCEEDED.
    # Dropping the now-served journal rows is best-effort cleanup — if it fails,
    # startup reconciliation will remove them (they reference committed emails, so
    # no secret is deleted). Never turn a durable creation into a failure response
    # here; that would invite a duplicate-run retry. Log only a safe counter — no
    # emails, secrets, refs, or exception text.
    try:
        with session_factory() as journal_session:
            journal_session.query(ShopCheckCredentialJournal).filter_by(
                run_id=run_id
            ).delete()
            journal_session.commit()
    except Exception:
        _logger.warning(
            "shop_check: post-success journal cleanup failed for run %s; "
            "startup reconciliation will remove the served rows",
            run_id,
        )

    session.refresh(run)
    summary = {
        "total_lines": parsed.total_lines,
        "valid": len(parsed.valid),
        "duplicates": len(parsed.duplicates),
        "invalid": len(parsed.invalid),
        "worker_count": worker_count(len(parsed.valid), payload.emails_per_profile),
        # Counts above are exact; previews below are capped so the response never
        # balloons with a huge paste's rejects.
        "invalid_entries": [
            {"line": e.line, "masked": e.masked, "reason": e.reason}
            for e in parsed.invalid[:MAX_PREVIEW]
        ],
        "invalid_truncated": len(parsed.invalid) > MAX_PREVIEW,
        "duplicate_entries": [
            {"line": d.line, "masked": d.masked} for d in parsed.duplicates[:MAX_PREVIEW]
        ],
        "duplicate_truncated": len(parsed.duplicates) > MAX_PREVIEW,
    }
    return {"run": run_detail(session, run), "input_summary": summary}


def reconcile_orphan_credentials(session_factory, store: CredentialStore) -> int:
    """Startup backstop for partially provisioned credentials.

    Deletes CredentialStore entries recorded in the journal that no COMMITTED
    email row references (orphans from a rolled-back run whose immediate
    compensation failed). Referenced secrets are never touched. Idempotent: a
    store delete that fails leaves the journal row for the next startup; a served
    journal row (its ref is now referenced) is simply cleared. Never logs a
    secret value — only opaque ref ids would ever be surfaced. Returns the number
    of orphan secrets removed.
    """
    removed = 0
    with session_factory() as session:
        entries = session.scalars(select(ShopCheckCredentialJournal)).all()
        for entry in entries:
            referenced = session.scalar(
                select(ShopCheckEmail.id).where(
                    ShopCheckEmail.credential_ref == entry.ref
                )
            )
            if referenced is not None:
                session.delete(entry)  # served its purpose; keep the live secret
                continue
            try:
                store.delete(entry.ref)
            except Exception:
                continue  # leave the journal row; retry on the next startup
            session.delete(entry)
            removed += 1
        session.commit()
    return removed


def promote_run_running(session: Session, run_id: str) -> None:
    """preparing -> running once a worker starts launching. Atomic + idempotent."""
    session.execute(
        update(ShopCheckRun)
        .where(ShopCheckRun.id == run_id, ShopCheckRun.status == "preparing")
        .values(status="running")
    )
    session.commit()


def finalize_email(
    session: Session,
    email: ShopCheckEmail,
    result: str,
    *,
    phone_prefix: str | None = None,
    phone_suffix: str | None = None,
    phone_country_code: str | None = None,
    phone_country_name: str | None = None,
    phone_region_name: str | None = None,
    phone_confidence: str | None = None,
) -> None:
    """Move one email to its terminal result coherently (state + result +
    checked_at together, satisfying the coherence constraint)."""
    email.state = "terminal"
    email.result = result
    email.checked_at = utc_now()
    email.phone_prefix = phone_prefix
    email.phone_suffix = phone_suffix
    email.phone_country_code = phone_country_code
    email.phone_country_name = phone_country_name
    email.phone_region_name = phone_region_name
    email.phone_confidence = phone_confidence
    session.commit()


def terminate_worker_emails(session: Session, worker_id: str, result: str) -> int:
    """Terminate every still-non-terminal email of a worker with `result` (used
    when a worker stops early: proxy_failed, unknown, cancelled). Returns count."""
    emails = session.scalars(
        select(ShopCheckEmail).where(
            ShopCheckEmail.worker_id == worker_id, ShopCheckEmail.state != "terminal"
        )
    ).all()
    now = utc_now()
    for email in emails:
        email.state = "terminal"
        email.result = result
        email.checked_at = now
    session.commit()
    return len(emails)


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

    The route calls this through the coordinator so a live run's workers also get
    the cancel signal; the persisted state here is the source of truth either way.
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
