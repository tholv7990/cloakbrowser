"""Profile factory: batch-create profiles, optionally kick off an automation run.

ponytail: mirrors the useful core of Quantum's factory (create N profiles from
the fingerprint template, then optionally run automation with one pooled
credential each). Proxy generation + per-item health-check-with-replacement are
deferred — profiles are created directly via the profiles service.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...models import (
    AutomationTemplate,
    ProfileFactoryItem,
    ProfileFactoryJob,
    utc_now,
)
from ..profiles.schemas import ProfileCreate
from ..profiles.service import create_profile
from .coordinator import RunCoordinator
from .schemas import RunAssignment
from .service import CREDENTIAL_VARIABLES, credential_summary, variables_from_steps


def job_to_dict(session: Session, job: ProfileFactoryJob) -> dict:
    items = session.scalars(
        select(ProfileFactoryItem)
        .where(ProfileFactoryItem.job_id == job.id)
        .order_by(ProfileFactoryItem.id)
    ).all()
    return {
        "id": job.id,
        "status": job.status,
        "quantity": job.quantity,
        "name_prefix": job.name_prefix,
        "automation_template_id": job.automation_template_id,
        "start_automation": job.start_automation,
        "created_count": job.created_count,
        "failed_count": job.failed_count,
        "created_at": job.created_at,
        "items": [
            {
                "id": item.id,
                "profile_id": item.profile_id,
                "status": item.status,
                "message": item.message,
            }
            for item in items
        ],
    }


class FactoryCoordinator:
    def __init__(self, session_factory, run_coordinator: RunCoordinator):
        self._session_factory = session_factory
        self._runs = run_coordinator
        self._lock = threading.Lock()
        self._executors: dict[str, ThreadPoolExecutor] = {}
        self._cancel: dict[str, threading.Event] = {}

    def _cancel_event(self, job_id: str) -> threading.Event:
        with self._lock:
            return self._cancel.setdefault(job_id, threading.Event())

    def shutdown(self) -> None:
        with self._lock:
            executors = list(self._executors.values())
            self._executors.clear()
        for executor in executors:
            executor.shutdown(wait=False, cancel_futures=True)

    def list_jobs(self, session: Session) -> list[dict]:
        jobs = session.scalars(
            select(ProfileFactoryJob).order_by(ProfileFactoryJob.created_at.desc())
        ).all()
        return [job_to_dict(session, job) for job in jobs]

    def get_job(self, session: Session, job_id: str) -> dict:
        job = session.get(ProfileFactoryJob, job_id)
        if job is None:
            raise ManagerError("factory_job_not_found", "The requested job was not found.", 404)
        return job_to_dict(session, job)

    def start(
        self,
        session: Session,
        *,
        quantity: int,
        name_prefix: str,
        automation_template_id: str | None,
        start_automation: bool,
    ) -> dict:
        if start_automation:
            if not automation_template_id:
                raise ManagerError(
                    "automation_template_required",
                    "Choose an automation template to start after creation.",
                    400,
                )
            template = session.get(AutomationTemplate, automation_template_id)
            if template is None:
                raise ManagerError("template_not_found", "The template was not found.", 404)
            template_vars = set(variables_from_steps(list(template.steps_json or [])))
            if not set(CREDENTIAL_VARIABLES) <= template_vars:
                raise ManagerError(
                    "automation_requires_credentials",
                    "The automation must use email and password variables to run in the factory.",
                    400,
                )
            if credential_summary(session)["available"] < quantity:
                raise ManagerError(
                    "insufficient_credentials",
                    "Import at least one pooled credential per profile before starting.",
                    400,
                )

        job = ProfileFactoryJob(
            status="running",
            quantity=quantity,
            name_prefix=name_prefix.strip(),
            automation_template_id=automation_template_id,
            start_automation=start_automation,
        )
        session.add(job)
        session.flush()
        item_ids = []
        for _ in range(quantity):
            item = ProfileFactoryItem(job_id=job.id, status="pending")
            session.add(item)
            session.flush()
            item_ids.append(item.id)
        session.commit()
        job_id = job.id

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"factory-{job_id[:8]}")
        with self._lock:
            self._executors[job_id] = executor
        executor.submit(
            self._build, job_id, name_prefix.strip(), item_ids, automation_template_id, start_automation
        )
        return self.get_job(session, job_id)

    def _build(self, job_id, name_prefix, item_ids, template_id, start_automation) -> None:
        created: list[str] = []
        cancel = self._cancel_event(job_id)
        with self._session_factory() as session:
            for index, item_id in enumerate(item_ids, start=1):
                item = session.get(ProfileFactoryItem, item_id)
                if cancel.is_set():
                    item.status = "cancelled"
                    session.commit()
                    continue
                try:
                    profile = create_profile(
                        session, ProfileCreate(name=f"{name_prefix} {index}")
                    )
                    item.profile_id = profile.id
                    item.status = "completed"
                    created.append(profile.id)
                except Exception as error:  # keep going; one bad profile ≠ whole batch
                    item.status = "failed"
                    item.message = str(error)[:500]
                session.commit()
            self._recompute(session, job_id)

        if start_automation and template_id and created and not cancel.is_set():
            with self._session_factory() as session:
                template = session.get(AutomationTemplate, template_id)
                if template is not None:
                    assignments = [RunAssignment(profile_id=pid) for pid in created]
                    try:
                        self._runs.start(
                            session, template, assignments, min(len(assignments), 5)
                        )
                    except ManagerError:
                        pass  # the run's own failure does not fail the factory job
        self._finalize(job_id)

    def _recompute(self, session: Session, job_id: str) -> None:
        job = session.get(ProfileFactoryJob, job_id)
        items = session.scalars(
            select(ProfileFactoryItem).where(ProfileFactoryItem.job_id == job_id)
        ).all()
        job.created_count = sum(1 for i in items if i.status == "completed")
        job.failed_count = sum(1 for i in items if i.status == "failed")
        session.commit()

    def _finalize(self, job_id: str) -> None:
        with self._lock:
            cancelled = self._cancel.get(job_id) is not None and self._cancel[job_id].is_set()
        with self._session_factory() as session:
            self._recompute(session, job_id)
            job = session.get(ProfileFactoryJob, job_id)
            if cancelled:
                job.status = "cancelled"
            elif job.failed_count == job.quantity:
                job.status = "failed"
            else:
                job.status = "completed"
            session.commit()

    def cancel(self, session: Session, job_id: str) -> dict:
        job = session.get(ProfileFactoryJob, job_id)
        if job is None:
            raise ManagerError("factory_job_not_found", "The requested job was not found.", 404)
        self._cancel_event(job_id).set()
        for item in session.scalars(
            select(ProfileFactoryItem).where(
                ProfileFactoryItem.job_id == job_id, ProfileFactoryItem.status == "pending"
            )
        ):
            item.status = "cancelled"
        if job.status == "running":
            job.status = "cancelled"
        session.commit()
        return self.get_job(session, job_id)
