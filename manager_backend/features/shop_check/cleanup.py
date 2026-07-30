"""Manual, exact-scope cleanup of a Shop-check run's owned profiles.

Only profiles this run OWNS are touched, and ownership comes exclusively from the
immutable `shop_check_workers.profile_id` provenance — never a name, tag, or
client-supplied id/path. For each owned profile: stop its runtime, remove the
profile directory (resolved through the containment-checked resolver, so it can
never escape the profile root), then delete the DB row (FK-cascades its
children). Proxies, worker/email results, and exports are preserved.

Each profile is deleted independently and progress is persisted: a filesystem
failure marks that one profile failed and leaves its row intact (retryable),
while the rest still complete. The directory is removed BEFORE the row so a
failed unlink never orphans a still-referenced-but-gone profile.
"""

from __future__ import annotations

import logging
import shutil
import time

from sqlalchemy import select

from ...config import ManagerSettings
from ...errors import ManagerError
from ...features.profiles.directories import resolve_profile_directory
from ...models import Profile, RuntimeSession, ShopCheckWorker
from . import service
from .sanitize import sanitize_error

_logger = logging.getLogger(__name__)

# Runtime states that still hold the profile's files. Deleting the directory
# while any of these is live corrupts the profile (and fails on Windows).
_ACTIVE_RUNTIME_STATES = frozenset({"queued", "starting", "running", "stopping", "detached"})
_DEFAULT_STOP_TIMEOUT = 10.0


class RuntimeStillActiveError(Exception):
    """The owned runtime did not stop in time, so its files are still locked."""


def _runtime_active(session, profile_id: str) -> bool:
    return (
        session.scalar(
            select(RuntimeSession.id).where(
                RuntimeSession.profile_id == profile_id,
                RuntimeSession.state.in_(_ACTIVE_RUNTIME_STATES),
            )
        )
        is not None
    )


def _stop_runtime_and_wait(runtime_manager, session_factory, profile_id: str, timeout: float) -> None:
    """Stop the profile's runtime and block until it has actually exited.

    RuntimeManager.stop() only *requests* a stop (the worker tears the browser
    down on its own thread), so we must wait for the runtime to leave its active
    states before deleting the directory. Raises if it will not stop in time.
    """
    runtime_manager.stop(profile_id)
    if session_factory is None:
        return  # caller opted out of the readiness wait (no runtime to observe)
    deadline = time.monotonic() + timeout
    while True:
        with session_factory() as session:
            if not _runtime_active(session, profile_id):
                return
        if time.monotonic() >= deadline:
            raise RuntimeStillActiveError(
                "The profile's browser is still running; it cannot be deleted yet."
            )
        time.sleep(0.05)


def resolve_owned_profile_ids(session, run_id: str) -> list[str]:
    """Owned profile ids for a run, from immutable worker ownership, ordered."""
    return list(
        session.scalars(
            select(ShopCheckWorker.profile_id)
            .where(
                ShopCheckWorker.run_id == run_id,
                ShopCheckWorker.profile_id.is_not(None),
            )
            .order_by(ShopCheckWorker.ordinal)
        )
    )


def _delete_owned_profile(session, settings: ManagerSettings, profile_id: str) -> None:
    # Resolver enforces canonical-UUID + containment under the profile root.
    directory = resolve_profile_directory(settings, profile_id)
    if directory.exists():
        shutil.rmtree(directory)  # remove disk state first; row stays if this raises
    profile = session.get(Profile, profile_id)
    if profile is not None:
        session.delete(profile)  # FK cascade removes children
    session.commit()


def cleanup_run(
    session,
    settings: ManagerSettings,
    runtime_manager,
    run_id: str,
    *,
    expected_profile_count: int,
    session_factory=None,
    stop_timeout_seconds: float = _DEFAULT_STOP_TIMEOUT,
) -> dict:
    run = service.require_run(session, run_id)
    # Cleanup deletes the run's temporary profiles — only ever safe once the run
    # has finished. A direct API caller must not delete profiles out from under
    # workers that are still queued/preparing/running.
    if run.status not in service.TERMINAL_RUN_STATES:
        raise ManagerError(
            "shop_check_cleanup_run_active",
            "The run is still in progress; cleanup is available once it finishes or is cancelled.",
            409,
        )
    owned = resolve_owned_profile_ids(session, run_id)
    if len(owned) != expected_profile_count:
        # A stale UI must never delete a different count than it displayed.
        raise ManagerError(
            "shop_check_cleanup_count_mismatch",
            "The owned-profile count changed since it was displayed; refresh and retry.",
            409,
        )

    run.cleanup_state = "in_progress"
    session.commit()

    results: list[dict] = []
    deleted = 0
    failed = 0
    for profile_id in owned:
        try:
            # Stop the owned runtime and WAIT for it to exit before deleting, so
            # the directory is never rmtree'd while the browser still locks it.
            _stop_runtime_and_wait(runtime_manager, session_factory, profile_id, stop_timeout_seconds)
            _delete_owned_profile(session, settings, profile_id)
            results.append({"profile_id": profile_id, "deleted": True, "error": None})
            deleted += 1
        except Exception as error:
            session.rollback()
            _logger.warning("shop_check: cleanup failed for one profile of run %s", run_id)
            results.append(
                {"profile_id": profile_id, "deleted": False, "error": sanitize_error(error)}
            )
            failed += 1

    run.cleanup_state = "done" if failed == 0 else "partial"
    session.commit()
    return {
        "run_id": run_id,
        "cleanup_state": run.cleanup_state,
        "requested": len(owned),
        "deleted": deleted,
        "failed": failed,
        "profiles": results,
    }
