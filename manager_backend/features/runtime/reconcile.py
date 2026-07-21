from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlparse

import psutil
from sqlalchemy import select

from ...config import ManagerSettings
from ...models import RuntimeSession
from .logs import append_profile_log
from .service import ACTIVE_STATES, transition_runtime


Inspection = Literal["missing", "unsafe", "owned"]


def _owner_is_live(metadata: dict) -> bool:
    pid = metadata.get("manager_pid")
    created_at = metadata.get("manager_created_at")
    if not isinstance(pid, int) or not isinstance(created_at, (int, float)):
        return True
    try:
        process = psutil.Process(pid)
        return process.is_running() and abs(process.create_time() - created_at) < 1.0
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    except (psutil.AccessDenied, OSError):
        return True


def cleanup_stale_locks(
    settings: ManagerSettings,
    *,
    owner_is_live: Callable[[dict], bool] = _owner_is_live,
) -> int:
    removed = 0
    if not settings.profile_root.exists():
        return removed
    for lock_path in settings.profile_root.glob("*/.runtime.lock"):
        try:
            metadata = json.loads(lock_path.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                continue
            if metadata.get("profile_id") != lock_path.parent.name:
                continue
            if owner_is_live(metadata):
                continue
            lock_path.unlink()
            removed += 1
        except (OSError, ValueError, TypeError):
            continue
    return removed


class ProcessInspector(Protocol):
    def inspect(self, runtime: RuntimeSession, profile_dir: Path) -> Inspection: ...


class PsutilProcessInspector:
    def inspect(self, runtime: RuntimeSession, profile_dir: Path) -> Inspection:
        if runtime.browser_pid is None or runtime.browser_created_at is None:
            return "missing"
        try:
            process = psutil.Process(runtime.browser_pid)
            if not process.is_running():
                return "missing"
            created_matches = abs(
                process.create_time() - runtime.browser_created_at.timestamp()
            ) < 1.0
            command_line = " ".join(process.cmdline()).casefold()
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return "missing"
        except (psutil.AccessDenied, OSError):
            return "unsafe"
        owned_path = str((profile_dir / "user-data").resolve()).casefold()
        if not created_matches or owned_path not in command_line:
            return "unsafe"
        endpoint = urlparse(runtime.cdp_endpoint or "")
        if endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return "unsafe"
        return "owned"


def reconcile_runtimes(
    session_factory,
    settings: ManagerSettings,
    *,
    inspector: ProcessInspector | None = None,
    reconnect: Callable[[RuntimeSession], bool] | None = None,
) -> dict[str, int]:
    process_inspector = inspector or PsutilProcessInspector()
    try_reconnect = reconnect or (lambda _runtime: False)
    summary = {"crashed": 0, "detached": 0, "reconnected": 0}
    with session_factory() as session:
        runtimes = list(
            session.scalars(
                select(RuntimeSession).where(RuntimeSession.state.in_(ACTIVE_STATES))
            )
        )
        for runtime in runtimes:
            profile_dir = settings.profile_root / runtime.profile_id
            inspection = process_inspector.inspect(runtime, profile_dir)
            if inspection == "missing":
                transition_runtime(
                    session, runtime, "crashed", message="manager_restarted"
                )
                append_profile_log(
                    session,
                    runtime.profile_id,
                    "error",
                    "runtime.crashed",
                    settings=settings,
                )
                append_profile_log(
                    session,
                    runtime.profile_id,
                    "info",
                    "runtime.reconciled",
                    settings=settings,
                )
                summary["crashed"] += 1
            elif inspection == "owned" and try_reconnect(runtime):
                runtime.state = "running"
                runtime.last_message = "browser_reconnected"
                session.commit()
                session.refresh(runtime)
                append_profile_log(
                    session,
                    runtime.profile_id,
                    "info",
                    "runtime.reconciled",
                    settings=settings,
                )
                summary["reconnected"] += 1
            else:
                transition_runtime(
                    session, runtime, "detached", message="browser_detached"
                )
                append_profile_log(
                    session,
                    runtime.profile_id,
                    "warning",
                    "runtime.reconciled",
                    settings=settings,
                )
                summary["detached"] += 1
    return summary
