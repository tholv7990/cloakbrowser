from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...dependencies import get_session
from ...errors import ManagerError
from ...models import RuntimeSession
from .schemas import RuntimePage, RuntimeRead


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
