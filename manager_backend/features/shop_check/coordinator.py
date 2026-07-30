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
from .launcher import RuntimeLaunchError, RuntimeLauncher
from .provisioner import ProxyProvisionError, group_workers, provision_profile, provision_proxy

_TERMINAL_WORKER = "terminal"
# How long to wait for a launched runtime to become drivable before failing the
# worker (proxy preflight + Chromium boot + CDP endpoint write).
_DEFAULT_LAUNCH_TIMEOUT = 90.0


@dataclass
class WorkerContext:
    """Handed to the injected `process_worker`. Carries no secrets; the callback
    resolves a single email's full address from CredentialStore only when it is
    actively processing that email. `cdp_endpoint` is the live loopback CDP URL of
    the already-ready browser, so the callback can drive the page immediately."""

    run_id: str
    worker_id: str
    profile_id: str
    email_ids: list[str]
    session_factory: Callable
    store: object
    is_cancelled: Callable[[], bool]
    cdp_endpoint: str | None = None


class ShopCheckCoordinator:
    def __init__(
        self,
        session_factory,
        store,
        provider_client,
        tester,
        launcher: RuntimeLauncher,
        process_worker: Callable[[WorkerContext], None],
        *,
        launch_timeout_seconds: float = _DEFAULT_LAUNCH_TIMEOUT,
    ):
        # process_worker is REQUIRED: a coordinator with no real page automation
        # would launch a browser, do nothing, and leave every email pending. Tests
        # pass an explicit fake/no-op; production passes make_process_worker(...).
        if process_worker is None:
            raise ValueError(
                "ShopCheckCoordinator requires a process_worker; a missing "
                "processor would terminalize workers with their emails still pending."
            )
        self._session_factory = session_factory
        self._store = store
        self._provider_client = provider_client
        self._tester = tester
        self._launcher = launcher
        self._process_worker = process_worker
        self._launch_timeout = launch_timeout_seconds
        self._lock = threading.Lock()
        self._executors: dict[str, ThreadPoolExecutor] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._futures: set[Future] = set()
        # Worker ids currently submitted/running — guards against a duplicate
        # submit (e.g. startup recovery racing a still-running worker).
        self._inflight: set[str] = set()

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

    def _submit(self, executor: ThreadPoolExecutor, run_id: str, worker_id: str) -> Future | None:
        with self._lock:
            if worker_id in self._inflight:
                return None  # already submitted/running — never double-process
            self._inflight.add(worker_id)
        future = executor.submit(self._run_worker, run_id, worker_id)

        def _done(f: Future) -> None:
            with self._lock:
                self._futures.discard(f)
                self._inflight.discard(worker_id)

        with self._lock:
            self._futures.add(future)
        future.add_done_callback(_done)
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
            worker = session.get(ShopCheckWorker, worker_id)

            # Resume: a worker that already owns a proxy + profile (from before a
            # restart) skips provisioning — recovery never generates a duplicate
            # proxy or profile.
            if worker.proxy_id and worker.profile_id:
                proxy_id, profile_id = worker.proxy_id, worker.profile_id
            else:
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
                    self._fail_worker(
                        session, worker_id, f"proxy_{error.category}", "proxy_failed"
                    )
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

            # 3) launching — block until Chromium is running with a live CDP
            # endpoint. On launch failure the launcher has already stopped it.
            self._set_state(session, worker_id, "launching")
            service.promote_run_running(session, run_id)
            if self._is_cancelled(run_id):
                self._cancel_worker(session, worker_id)
                return
            try:
                cdp_endpoint = self._launcher.start_and_wait_ready(
                    profile_id,
                    timeout_seconds=self._launch_timeout,
                    is_cancelled=lambda: self._is_cancelled(run_id),
                )
            except RuntimeLaunchError as error:
                if self._is_cancelled(run_id) or error.reason == "cancelled":
                    self._cancel_worker(session, worker_id)
                else:
                    self._fail_worker(
                        session, worker_id, f"launch_{error.reason}", "navigation_failed"
                    )
                return

            # The runtime is up and owned by us; from here it MUST be stopped on
            # every exit path (success, cancel, or an unexpected error).
            try:
                # 4) processing (injected page automation)
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
                    cdp_endpoint=cdp_endpoint,
                )
                self._process_worker(ctx)
            finally:
                # 5) stopping — always tear the browser down.
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

    # --- startup recovery ---------------------------------------------------
    def recover(self, session_factory=None) -> int:
        """Re-enqueue non-terminal workers of runs interrupted mid-flight
        (status preparing/running). Resume-safe: the in-flight guard and the
        proxy/profile checkpoints make a re-submit idempotent, and a re-submit of
        a still-running worker is dropped. Returns the number of workers resumed.
        """
        factory = session_factory or self._session_factory
        resumed = 0
        with factory() as session:
            runs = session.scalars(
                select(ShopCheckRun).where(
                    ShopCheckRun.status.in_(["preparing", "running"])
                )
            ).all()
            plan = [
                (run.id, run.max_parallel, [
                    worker.id
                    for worker in session.scalars(
                        select(ShopCheckWorker).where(
                            ShopCheckWorker.run_id == run.id,
                            ShopCheckWorker.state != _TERMINAL_WORKER,
                        )
                    )
                ])
                for run in runs
            ]
        for run_id, max_parallel, worker_ids in plan:
            executor = self._executor(run_id, max_parallel)
            for worker_id in worker_ids:
                if self._submit(executor, run_id, worker_id) is not None:
                    resumed += 1
        return resumed
