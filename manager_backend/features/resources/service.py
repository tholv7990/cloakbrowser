from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import psutil
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Profile, RuntimeSession
from ..runtime.service import ACTIVE_STATES

# Whole-snapshot cache so 2s polling never triggers back-to-back process scans.
_CACHE_SECONDS = 0.8
_cache: tuple[float, dict[str, Any]] | None = None
_cache_lock = threading.Lock()

# Persist Process objects across snapshots so cpu_percent(interval=None) reports a
# real delta since the previous poll instead of 0.0 for a fresh object.
_proc_cache: dict[int, psutil.Process] = {}
_backend_proc = psutil.Process(os.getpid())


def _process(pid: int) -> psutil.Process | None:
    proc = _proc_cache.get(pid)
    if proc is not None:
        try:
            if proc.is_running():
                return proc
        except (psutil.Error, OSError):
            pass
        _proc_cache.pop(pid, None)
    try:
        proc = psutil.Process(pid)
        proc.cpu_percent(interval=None)  # prime; first reading is 0.0
    except (psutil.Error, OSError):
        return None
    _proc_cache[pid] = proc
    return proc


def _tree(root_pid: int) -> list[psutil.Process]:
    root = _process(root_pid)
    if root is None:
        return []
    procs = [root]
    try:
        for child in root.children(recursive=True):
            cached = _process(child.pid)
            if cached is not None:
                procs.append(cached)
    except (psutil.Error, OSError):
        pass
    return procs


def _summarize(procs: list[psutil.Process], logical_cpus: int) -> dict[str, Any]:
    unique = {proc.pid: proc for proc in procs}
    cpu = 0.0
    memory = 0
    for proc in unique.values():
        try:
            # Divide by logical cores so a busy multi-thread browser reads 0-100.
            cpu += float(proc.cpu_percent(interval=None)) / logical_cpus
            memory += int(proc.memory_info().rss)
        except (psutil.Error, OSError, ValueError):
            continue
    return {"cpu_percent": round(max(0.0, cpu), 1), "memory_bytes": memory, "process_count": len(unique)}


def build_snapshot(session: Session) -> dict[str, Any]:
    global _cache
    now = time.time()
    with _cache_lock:
        if _cache is not None and now - _cache[0] < _CACHE_SECONDS:
            return _cache[1]

        logical = max(1, int(psutil.cpu_count(logical=True) or 1))
        vm = psutil.virtual_memory()
        system = {
            "cpu_percent": round(max(0.0, float(psutil.cpu_percent(interval=None))), 1),
            "memory_percent": round(float(vm.percent), 1),
            "memory_used_bytes": int(vm.used),
            "memory_total_bytes": int(vm.total),
            "logical_cpus": logical,
        }
        backend = _summarize([_backend_proc], logical)

        runtimes = session.scalars(
            select(RuntimeSession).where(RuntimeSession.state.in_(ACTIVE_STATES))
        ).all()
        profile_rows: list[dict[str, Any]] = []
        all_browser: dict[int, psutil.Process] = {}
        for runtime in runtimes:
            if runtime.browser_pid is None:
                continue
            procs = _tree(runtime.browser_pid)
            if not procs:
                continue
            for proc in procs:
                all_browser[proc.pid] = proc
            profile = session.get(Profile, runtime.profile_id)
            profile_rows.append(
                {
                    **_summarize(procs, logical),
                    "profile_id": runtime.profile_id,
                    "profile_name": profile.name if profile is not None else runtime.profile_id,
                    "runtime_state": runtime.state,
                }
            )
        profile_rows.sort(
            key=lambda row: (float(row["cpu_percent"]), int(row["memory_bytes"])), reverse=True
        )
        browsers = {**_summarize(list(all_browser.values()), logical), "profiles_running": len(profile_rows)}

        snapshot = {
            "generated_at": datetime.now(timezone.utc),
            "system": system,
            "backend": backend,
            "browsers": browsers,
            "profiles": profile_rows,
        }
        _cache = (now, snapshot)
        # Drop dead entries so the cache doesn't grow unbounded.
        for pid, proc in list(_proc_cache.items()):
            try:
                if not proc.is_running():
                    _proc_cache.pop(pid, None)
            except (psutil.Error, OSError):
                _proc_cache.pop(pid, None)
        return snapshot


_ONGOING_STATES = frozenset({"queued", "starting", "running", "stopping", "detached"})


def _exit_reason(runtime: RuntimeSession) -> str | None:
    if runtime.state in _ONGOING_STATES:
        return None
    if runtime.state == "crashed":
        return "crashed"
    if runtime.state == "stopped":
        return "stopped"
    return "unknown"


def list_sessions(session: Session, limit: int = 25) -> list[dict[str, Any]]:
    runtimes = session.scalars(
        select(RuntimeSession)
        .order_by(RuntimeSession.created_at.desc(), RuntimeSession.id)
        .limit(limit)
    ).all()
    records: list[dict[str, Any]] = []
    for runtime in runtimes:
        profile = session.get(Profile, runtime.profile_id)
        duration = None
        if runtime.started_at is not None and runtime.stopped_at is not None:
            duration = max(0, int((runtime.stopped_at - runtime.started_at).total_seconds()))
        startup_ms = None
        if runtime.started_at is not None and runtime.created_at is not None:
            startup_ms = max(0, int((runtime.started_at - runtime.created_at).total_seconds() * 1000))
        records.append(
            {
                "id": runtime.id,
                "profile_id": runtime.profile_id,
                "profile_name": profile.name if profile is not None else runtime.profile_id,
                "started_at": runtime.started_at or runtime.created_at,
                "ended_at": runtime.stopped_at,
                "duration_seconds": duration,
                "startup_ms": startup_ms,
                "exit_reason": _exit_reason(runtime),
            }
        )
    return records
