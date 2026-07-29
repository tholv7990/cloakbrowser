"""Shop-check run coordinator.

Claims a queued run, groups its emails into workers, and drives each worker
(proxy -> profile+ownership -> launch -> process -> stop) on a bounded thread
pool. One DB session per worker thread; run/worker/email transitions are
persisted; aggregate counts are recomputed from rows. Cancellation, startup
recovery, and clean shutdown mirror the proven automation coordinator.

The per-email page work is an injected `process_worker(ctx)` callback — this
checkpoint does NOT implement browser-page automation; tests pass a fake.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import wait as futures_wait
from dataclasses import dataclass
from collections.abc import Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...models import ShopCheckEmail, ShopCheckRun, ShopCheckWorker, utc_now
from . import service
from .launcher import RuntimeLauncher
from .provisioner import ProxyProvisionError, group_workers, provision_profile, provision_proxy

_TERMINAL_WORKER = "terminal"


@dataclass
class WorkerContext:
    """Handed to the injected `process_worker`. Carries no secrets; the callback
    resolves a single email's full address from CredentialStore only when it is
    actively processing that email (later browser checkpoint)."""

    run_id: str
    worker_id: str
    profile_id: str
    email_ids: list[str]
    session_factory: Callable
    store: object
    is_cancelled: Callable[[], bool]


def _noop_process_worker(ctx: "WorkerContext") -> None:
    """Default: no per-email work (page automation is a later checkpoint). Leaves
    the worker's emails pending; a real process_worker terminates them."""
    return None


class ShopCheckCoordinator:
    def __init__(
        self,
        session_factory,
        store,
        provider_client,
        tester,
        launcher: RuntimeLauncher,
        process_worker: Callable[[WorkerContext], None] | None = None,
    ):
        self._session_factory = session_factory
        self._store = store
        self._provider_client = provider_client
        self._tester = tester
        self._launcher = launcher
        self._process_worker = process_worker or _noop_process_worker
        self._lock = threading.Lock()
        self._executors: dict[str, ThreadPoolExecutor] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._futures: set[Future] = set()

    # --- registries ---------------------------------------------------------
    def _cancel_event(self, run_id: str) -> threading.Event:
        with self._lock:
            return self._cancel.setdefault(run_id, threading.Event())

    def _is_cancelled(self, run_id: str) -> bool:
        return self._cancel_event(run_id).is_set()

    def _executor(self, run_id: str, max_parallel: int) -> ThreadPoolExecutor:
        with self._lock:
            executor = self._executors.get(run_id)
            if executor is None:
                executor = ThreadPoolExecutor(
                    max_workers=max(1, min(max_parallel, 5)),
                    thread_name_prefix=f"shopchk-{run_id[:8]}",
                )
                self._executors[run_id] = executor
            return executor

    def _submit(self, executor: ThreadPoolExecutor, run_id: str, worker_id: str) -> Future:
        future = executor.submit(self._run_worker, run_id, worker_id)
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(lambda f: self._futures.discard(f))
        return future

    def shutdown(self, timeout: float = 10.0) -> bool:
        with self._lock:
            for event in self._cancel.values():
                event.set()
            executors = list(self._executors.values())
            self._executors.clear()
            pending = set(self._futures)
        for executor in executors:
            executor.shutdown(wait=False, cancel_futures=True)
        if not pending:
            return True
        _, not_done = futures_wait(pending, timeout=timeout)
        return not not_done

    # --- start --------------------------------------------------------------
    def start(self, session: Session, run_id: str) -> dict:
        # Atomic claim: only the queued->preparing winner provisions. A duplicate
        # start finds rowcount 0 and simply returns the current detail.
        claimed = session.execute(
            update(ShopCheckRun)
            .where(ShopCheckRun.id == run_id, ShopCheckRun.status == "queued")
            .values(status="preparing", started_at=utc_now())
        ).rowcount
        session.commit()
        if not claimed:
            return service.get_run_detail(session, run_id)

        group_workers(session, run_id)
        run = service.require_run(session, run_id)
        worker_ids = [
            w.id
            for w in session.scalars(
                select(ShopCheckWorker)
                .where(ShopCheckWorker.run_id == run_id)
                .order_by(ShopCheckWorker.ordinal)
            )
        ]
        executor = self._executor(run_id, run.max_parallel)
        for worker_id in worker_ids:
            self._submit(executor, run_id, worker_id)
        return service.get_run_detail(session, run_id)

    # --- per-worker driver --------------------------------------------------
    def _set_state(self, session: Session, worker_id: str, state: str) -> None:
        worker = session.get(ShopCheckWorker, worker_id)
        if worker is not None:
            worker.state = state
            session.commit()

    def _run_worker(self, run_id: str, worker_id: str) -> None:
        session = self._session_factory()
        try:
            if self._is_cancelled(run_id):
                self._cancel_worker(session, worker_id)
                return
            run = session.get(ShopCheckRun, run_id)

            # 1) proxy_check
            self._set_state(session, worker_id, "proxy_check")
            try:
                proxy_id = provision_proxy(
                    self._session_factory,
                    self._store,
                    self._provider_client,
                    self._tester,
                    region=run.region,
                    is_cancelled=lambda: self._is_cancelled(run_id),
                )
            except ProxyProvisionError as error:
                if error.category == "cancelled":
                    self._cancel_worker(session, worker_id)
                    return
                self._fail_worker(session, worker_id, f"proxy_{error.category}", "proxy_failed")
                return

            # 2) profile_create (+ durable ownership)
            self._set_state(session, worker_id, "profile_create")
            profile_id = provision_profile(
                session,
                worker_id,
                proxy_id=proxy_id,
                target_url=run.target_url,
                name=self._profile_name(run, session, worker_id),
            )

            # 3) launching
            self._set_state(session, worker_id, "launching")
            service.promote_run_running(session, run_id)
            if self._is_cancelled(run_id):
                self._cancel_worker(session, worker_id)
                return
            self._launcher.start(profile_id)

            # 4) processing (injected; page automation is a later checkpoint)
            self._set_state(session, worker_id, "processing")
            email_ids = [
                e.id
                for e in session.scalars(
                    select(ShopCheckEmail)
                    .where(ShopCheckEmail.worker_id == worker_id)
                    .order_by(ShopCheckEmail.ordinal)
                )
            ]
            ctx = WorkerContext(
                run_id=run_id,
                worker_id=worker_id,
                profile_id=profile_id,
                email_ids=email_ids,
                session_factory=self._session_factory,
                store=self._store,
                is_cancelled=lambda: self._is_cancelled(run_id),
            )
            try:
                self._process_worker(ctx)
            finally:
                # 5) stopping
                self._set_state(session, worker_id, "stopping")
                try:
                    self._launcher.stop(profile_id)
                except Exception:
                    pass
            if self._is_cancelled(run_id):
                service.terminate_worker_emails(session, worker_id, "cancelled")
            self._set_state(session, worker_id, _TERMINAL_WORKER)
        except Exception as error:  # unexpected failure at any boundary
            self._fail_worker(session, worker_id, str(error), "unknown")
        finally:
            self._recompute(run_id)
            session.close()

    def _profile_name(self, run: ShopCheckRun, session: Session, worker_id: str) -> str:
        worker = session.get(ShopCheckWorker, worker_id)
        prefix = (run.profile_prefix or "ShopCheck").strip() or "ShopCheck"
        return f"{prefix} {worker.ordinal + 1}"[:80]

    def _fail_worker(self, session: Session, worker_id: str, message: str, email_result: str) -> None:
        worker = session.get(ShopCheckWorker, worker_id)
        if worker is None:
            return
        service.set_worker_error(worker, message)  # sanitized
        worker.state = _TERMINAL_WORKER
        session.commit()
        service.terminate_worker_emails(session, worker_id, email_result)

    def _cancel_worker(self, session: Session, worker_id: str) -> None:
        worker = session.get(ShopCheckWorker, worker_id)
        if worker is None:
            return
        worker.state = _TERMINAL_WORKER
        session.commit()
        service.terminate_worker_emails(session, worker_id, "cancelled")

    # --- recompute + cancel -------------------------------------------------
    def _recompute(self, run_id: str) -> None:
        with self._lock:
            with self._session_factory() as session:
                service.recompute_run(session, run_id)

    def cancel(self, session: Session, run_id: str) -> dict:
        self._cancel_event(run_id).set()
        return service.cancel_run(session, run_id)
