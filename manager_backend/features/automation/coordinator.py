"""Multi-profile run coordinator.

Validates assignments, atomically reserves pooled credentials, then drives one
replay per profile on a bounded thread pool. Each item reports progress and
human-gates through the injected controller; this class owns all DB state,
credential release, aggregate counts, and the per-item gate Events.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...models import (
    AutomationCredential,
    AutomationRun,
    AutomationRunItem,
    AutomationTemplate,
    Profile,
    utc_now,
)
from .controller import AutomationController, RunItemContext
from .service import (
    CREDENTIAL_VARIABLES,
    complete_credential,
    credential_secret,
    release_credential,
    reserve_credential,
    variables_from_steps,
)


_TERMINAL_ITEM = frozenset({"completed", "failed", "cancelled"})
_ACTIVE_ITEM = frozenset({"pending", "running", "attention"})


def _redact(message: str, secret: tuple[str, str] | None) -> str:
    text = str(message)
    if secret:
        for part in secret:
            if part:
                text = text.replace(part, "***")
    return text[:1000]


class RunCoordinator:
    def __init__(self, session_factory, credential_store, controller: AutomationController):
        self._session_factory = session_factory
        self._store = credential_store
        self._controller = controller
        self._lock = threading.Lock()
        self._executors: dict[str, ThreadPoolExecutor] = {}
        self._gates: dict[str, dict[str, threading.Event]] = {}
        self._cancel: dict[str, threading.Event] = {}

    # --- registries ---------------------------------------------------------
    def _cancel_event(self, run_id: str) -> threading.Event:
        with self._lock:
            return self._cancel.setdefault(run_id, threading.Event())

    def _gate_event(self, run_id: str, item_id: str) -> threading.Event:
        with self._lock:
            return self._gates.setdefault(run_id, {}).setdefault(item_id, threading.Event())

    def _is_cancelled(self, run_id: str) -> bool:
        return self._cancel_event(run_id).is_set()

    def _executor(self, run_id: str, max_parallel: int) -> ThreadPoolExecutor:
        with self._lock:
            executor = self._executors.get(run_id)
            if executor is None:
                executor = ThreadPoolExecutor(
                    max_workers=max(1, min(max_parallel, 5)),
                    thread_name_prefix=f"run-{run_id[:8]}",
                )
                self._executors[run_id] = executor
            return executor

    def shutdown(self) -> None:
        with self._lock:
            # Release any gate-blocked worker so its thread can exit.
            for event in self._cancel.values():
                event.set()
            for gates in self._gates.values():
                for event in gates.values():
                    event.set()
            executors = list(self._executors.values())
            self._executors.clear()
        for executor in executors:
            executor.shutdown(wait=False, cancel_futures=True)

    # --- start --------------------------------------------------------------
    def start(self, session: Session, template: AutomationTemplate, assignments, max_parallel: int) -> dict:
        profile_ids = [a.profile_id for a in assignments]
        if len(profile_ids) != len(set(profile_ids)):
            raise ManagerError("duplicate_profile", "A profile appears more than once.", 400)
        if len(profile_ids) > 50:
            raise ManagerError("too_many_profiles", "A run accepts at most 50 profiles.", 400)
        present = set(
            session.scalars(
                select(Profile.id).where(
                    Profile.id.in_(profile_ids), Profile.deleted_at.is_(None)
                )
            )
        )
        missing = [pid for pid in profile_ids if pid not in present]
        if missing:
            raise ManagerError(
                "profile_not_found", "One or more profiles do not exist.", 400,
                {"profiles": missing},
            )

        template_vars = variables_from_steps(list(template.steps_json or []))
        needs_credential = bool(set(CREDENTIAL_VARIABLES) & set(template_vars))
        custom_vars = [v for v in template_vars if v not in CREDENTIAL_VARIABLES]
        for assignment in assignments:
            absent = [v for v in custom_vars if v not in assignment.variables]
            if absent:
                raise ManagerError(
                    "missing_variables",
                    f"Profile {assignment.profile_id} is missing required variables.",
                    400,
                    {"variables": absent},
                )

        run = AutomationRun(
            template_id=template.id,
            status="running",
            max_parallel=max(1, min(max_parallel, 5)),
            total=len(assignments),
            started_at=utc_now(),
        )
        session.add(run)
        session.flush()

        item_ids: list[str] = []
        for assignment in assignments:
            item = AutomationRunItem(
                run_id=run.id,
                profile_id=assignment.profile_id,
                status="pending",
                # Persist only the template's DECLARED public variables — never a
                # credential (pool-resolved) and never a stray/secret request key.
                variables_json={
                    v: assignment.variables[v]
                    for v in custom_vars
                    if v in assignment.variables
                },
            )
            if needs_credential:
                ref = reserve_credential(
                    session,
                    run_id=run.id,
                    profile_id=assignment.profile_id,
                    credential_id=assignment.credential_id,
                )
                if ref is None:
                    session.rollback()
                    raise ManagerError(
                        "credential_unavailable",
                        "No pooled credential is available for every profile. Import more first.",
                        400,
                    )
                item.credential_ref = ref
            session.add(item)
            session.flush()
            item_ids.append(item.id)
        session.commit()
        run_id = run.id

        executor = self._executor(run_id, max_parallel)
        for item_id in item_ids:
            executor.submit(self._run_item, run_id, item_id, 0)
        return self.get_run(session, run_id)

    # --- per-item worker ----------------------------------------------------
    def _run_item(self, run_id: str, item_id: str, start_step: int) -> None:
        session = self._session_factory()
        try:
            item = session.get(AutomationRunItem, item_id)
            if item is None:
                return
            if self._is_cancelled(run_id):
                item.status = "cancelled"
                session.commit()
                # This worker owns the reservation until it terminates — release here
                # (the sole releaser), since cancel() never touches worker-owned creds.
                release_credential(session, run_id=run_id, profile_id=item.profile_id)
                self._recompute(run_id)
                return
            run = session.get(AutomationRun, run_id)
            template = session.get(AutomationTemplate, run.template_id)
            steps = list(template.steps_json or [])
            total = len(steps)
            item.status = "running"
            item.current_step = start_step
            item.error = None
            item.attention_reason = None
            session.commit()

            secret = credential_secret(self._store, item.credential_ref) if item.credential_ref else None
            variables = dict(item.variables_json or {})

            def set_progress(step: int) -> None:
                current = session.get(AutomationRunItem, item_id)
                current.last_completed_step = step
                current.current_step = min(step + 1, total)
                session.commit()

            def request_attention(reason: str) -> bool:
                return self._gate(run_id, item_id, reason)

            ctx = RunItemContext(
                run_id=run_id,
                profile_id=item.profile_id,
                steps=steps,
                variables=variables,
                secret=secret,
                start_step=start_step,
                set_progress=set_progress,
                request_attention=request_attention,
                is_cancelled=lambda: self._is_cancelled(run_id),
            )
            try:
                self._controller.run_item(ctx)
            except Exception as error:  # replay failure
                current = session.get(AutomationRunItem, item_id)
                current.status = "failed"
                current.error = _redact(str(error), secret)
                session.commit()
                release_credential(session, run_id=run_id, profile_id=current.profile_id)
            else:
                current = session.get(AutomationRunItem, item_id)
                if self._is_cancelled(run_id):
                    current.status = "cancelled"
                    session.commit()
                    release_credential(session, run_id=run_id, profile_id=current.profile_id)
                else:
                    current.status = "completed"
                    current.last_completed_step = total
                    current.current_step = total
                    current.error = None
                    current.attention_reason = None
                    session.commit()
                    complete_credential(session, run_id=run_id, profile_id=current.profile_id)
            self._recompute(run_id)
        finally:
            session.close()

    def _gate(self, run_id: str, item_id: str, reason: str) -> bool:
        with self._session_factory() as session:
            item = session.get(AutomationRunItem, item_id)
            item.status = "attention"
            item.attention_reason = reason
            session.commit()
        self._recompute(run_id)
        event = self._gate_event(run_id, item_id)
        event.clear()
        cancel = self._cancel_event(run_id)
        while not event.wait(0.1):
            if cancel.is_set():
                return False
        if cancel.is_set():
            return False
        with self._session_factory() as session:
            item = session.get(AutomationRunItem, item_id)
            item.status = "running"
            item.attention_reason = None
            session.commit()
        self._recompute(run_id)
        return True

    def _recompute(self, run_id: str) -> None:
        with self._lock:
            with self._session_factory() as session:
                run = session.get(AutomationRun, run_id)
                if run is None:
                    return
                items = session.scalars(
                    select(AutomationRunItem).where(AutomationRunItem.run_id == run_id)
                ).all()
                run.completed_count = sum(1 for i in items if i.status == "completed")
                run.failed_count = sum(1 for i in items if i.status == "failed")
                run.attention_count = sum(1 for i in items if i.status == "attention")
                active = any(i.status in _ACTIVE_ITEM for i in items)
                if self._cancel.get(run_id) is not None and self._cancel[run_id].is_set():
                    run.status = "cancelled"
                    if not active and run.finished_at is None:
                        run.finished_at = utc_now()
                elif not active:
                    run.status = "failed" if run.failed_count else "completed"
                    if run.finished_at is None:
                        run.finished_at = utc_now()
                else:
                    run.status = "running"
                session.commit()

    # --- controls -----------------------------------------------------------
    def _require_item(self, session: Session, run_id: str, profile_id: str) -> AutomationRunItem:
        item = session.scalar(
            select(AutomationRunItem).where(
                AutomationRunItem.run_id == run_id,
                AutomationRunItem.profile_id == profile_id,
            )
        )
        if item is None:
            raise ManagerError("run_item_not_found", "That profile is not part of this run.", 404)
        return item

    def continue_profile(self, session: Session, run_id: str, profile_id: str) -> dict:
        self._require_run(session, run_id)
        item = self._require_item(session, run_id, profile_id)
        self._gate_event(run_id, item.id).set()
        return self.get_run(session, run_id)

    def cancel(self, session: Session, run_id: str) -> dict:
        run = self._require_run(session, run_id)
        # Signal cancellation: wake any gated workers and flip the cancel token so
        # in-flight replays abort promptly. Credentials are NOT released here — each
        # item's worker owns its reservation and releases it when it terminates
        # (the sole releaser), so a cancel can never hand a live credential to
        # another run. Every item has a worker (submitted at start/retry), so no
        # reservation is orphaned by leaving it to the worker.
        self._cancel_event(run_id).set()
        for event in self._gates.get(run_id, {}).values():
            event.set()
        run.status = "cancelled"
        session.commit()
        self._recompute(run_id)
        return self.get_run(session, run_id)

    def retry_profile(self, session: Session, run_id: str, profile_id: str) -> dict:
        run = self._require_run(session, run_id)
        item = self._require_item(session, run_id, profile_id)
        if item.status not in {"failed", "cancelled"}:
            raise ManagerError("retry_not_allowed", "Only a failed profile can be retried.", 400)
        template = session.get(AutomationTemplate, run.template_id)
        needs_credential = bool(
            set(CREDENTIAL_VARIABLES) & set(variables_from_steps(list(template.steps_json or [])))
        )
        if needs_credential:
            ref = reserve_credential(
                session, run_id=run_id, profile_id=profile_id, credential_id=None
            )
            if ref is None:
                raise ManagerError(
                    "credential_unavailable", "No pooled credential is available to retry.", 400
                )
            item.credential_ref = ref
        start_step = item.last_completed_step
        item.status = "running"
        item.error = None
        run.status = "running"
        run.finished_at = None
        self._cancel_event(run_id).clear()
        session.commit()
        self._executor(run_id, run.max_parallel).submit(
            self._run_item, run_id, item.id, start_step
        )
        return self.get_run(session, run_id)

    def mark_completed(self, session: Session, run_id: str, profile_id: str) -> dict:
        run = self._require_run(session, run_id)
        item = self._require_item(session, run_id, profile_id)
        template = session.get(AutomationTemplate, run.template_id)
        total = len(list(template.steps_json or []))
        item.status = "completed"
        item.last_completed_step = total
        item.current_step = total
        item.error = None
        item.attention_reason = None
        session.commit()
        complete_credential(session, run_id=run_id, profile_id=profile_id)
        self._recompute(run_id)
        return self.get_run(session, run_id)

    # --- serialization ------------------------------------------------------
    def _require_run(self, session: Session, run_id: str) -> AutomationRun:
        run = session.get(AutomationRun, run_id)
        if run is None:
            raise ManagerError("run_not_found", "The requested run was not found.", 404)
        return run

    def get_run(self, session: Session, run_id: str) -> dict:
        session.expire_all()
        run = self._require_run(session, run_id)
        template = session.get(AutomationTemplate, run.template_id)
        total_steps = len(list(template.steps_json or [])) if template else 0
        items = session.scalars(
            select(AutomationRunItem)
            .where(AutomationRunItem.run_id == run_id)
            .order_by(AutomationRunItem.id)
        ).all()
        names = dict(
            session.execute(
                select(Profile.id, Profile.name).where(
                    Profile.id.in_([item.profile_id for item in items] or [""])
                )
            ).all()
        )
        return {
            "id": run.id,
            "template_id": run.template_id,
            "template_name": template.name if template else "",
            "status": run.status,
            "max_parallel": run.max_parallel,
            "total": run.total,
            "completed_count": run.completed_count,
            "failed_count": run.failed_count,
            "attention_count": run.attention_count,
            "created_at": run.created_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "items": [
                {
                    "profile_id": item.profile_id,
                    "profile_name": names.get(item.profile_id, item.profile_id),
                    "status": item.status,
                    "current_step": item.current_step,
                    "total_steps": total_steps,
                    "last_completed_step": item.last_completed_step,
                    "message": item.message,
                    "attention_reason": item.attention_reason,
                    "error": item.error,
                }
                for item in items
            ],
        }


def recover_interrupted_runs(session_factory) -> int:
    """On startup, fail interrupted runs/items and release their reserved creds."""
    with session_factory() as session:
        items = session.scalars(
            select(AutomationRunItem)
            .join(AutomationRun, AutomationRun.id == AutomationRunItem.run_id)
            .where(AutomationRun.status == "running")
        ).all()
        for item in items:
            if item.status in _ACTIVE_ITEM:
                item.status = "failed"
                item.error = item.error or "Interrupted by a restart."
        runs = session.scalars(
            select(AutomationRun).where(AutomationRun.status == "running")
        ).all()
        for run in runs:
            run.status = "failed"
            if run.finished_at is None:
                run.finished_at = utc_now()
        session.execute(
            update(AutomationCredential)
            .where(AutomationCredential.status == "reserved")
            .values(status="available", reserved_run_id=None, reserved_profile_id=None)
        )
        recovered = len(runs)
        session.commit()
    return recovered
