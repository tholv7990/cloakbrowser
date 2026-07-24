from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...dependencies import get_session
from ...errors import ManagerError
from ...models import RuntimeSession
from .schemas import (
    ArrangeRequest,
    ArrangeResponse,
    MonitorsResponse,
    RuntimePage,
    RuntimeRead,
)
from .windows import Monitor, arrange_windows, safe_profile_id


router = APIRouter()
SessionDependency = Annotated[Session, Depends(get_session)]


def runtime_to_dict(runtime: RuntimeSession) -> dict:
    return {
        "id": runtime.id,
        "profile_id": runtime.profile_id,
        "state": runtime.state,
        "last_message": runtime.last_message,
        "started_at": runtime.started_at,
        "stopped_at": runtime.stopped_at,
        "created_at": runtime.created_at,
        "updated_at": runtime.updated_at,
    }


@router.get("/runtimes", response_model=RuntimePage)
def list_runtimes(session: SessionDependency):
    items = list(
        session.scalars(
            select(RuntimeSession).order_by(RuntimeSession.created_at.desc(), RuntimeSession.id)
        )
    )
    return {
        "items": [runtime_to_dict(item) for item in items],
        "total": int(session.scalar(select(func.count(RuntimeSession.id))) or 0),
    }


@router.get("/runtimes/{runtime_id}", response_model=RuntimeRead)
def get_runtime(runtime_id: str, session: SessionDependency):
    runtime = session.get(RuntimeSession, runtime_id)
    if runtime is None:
        raise ManagerError("runtime_not_found", "The requested runtime was not found.", 404)
    return runtime_to_dict(runtime)


def _monitor_to_dict(monitor: Monitor) -> dict:
    wx, wy, ww, wh = monitor.work_area
    return {
        "id": monitor.id,
        "label": monitor.label,
        "width": monitor.width,
        "height": monitor.height,
        "work_area": {"x": wx, "y": wy, "width": ww, "height": wh},
        "is_primary": monitor.is_primary,
    }


def _select_monitor(monitors: list[Monitor], monitor_id: str) -> Monitor | None:
    if not monitors:
        return None
    for monitor in monitors:
        if monitor.id == monitor_id:
            return monitor
    for monitor in monitors:  # unknown id -> primary (stale dropdown is not an error)
        if monitor.is_primary:
            return monitor
    return monitors[0]


@router.get("/runtime/monitors", response_model=MonitorsResponse)
def list_monitors(request: Request):
    manager = request.app.state.window_manager
    return {"monitors": [_monitor_to_dict(m) for m in manager.list_monitors()]}


@router.post("/runtime/windows/arrange", response_model=ArrangeResponse)
def arrange(payload: ArrangeRequest, request: Request):
    manager = request.app.state.window_manager
    settings = request.app.state.settings
    monitor = _select_monitor(manager.list_monitors(), payload.monitor_id)
    if monitor is None:  # non-Windows / no displays -> feature inert
        return {
            "results": [
                {"profile_id": pid, "ok": False, "error": "not_running"}
                for pid in payload.profile_ids
            ]
        }
    items: list[tuple[str, str | None]] = []
    for pid in payload.profile_ids:
        if safe_profile_id(pid):
            items.append((pid, str(settings.profile_root / pid / "user-data")))
        else:
            items.append((pid, None))
    results = arrange_windows(items, monitor.work_area, payload.layout, manager)
    return {"results": results}
