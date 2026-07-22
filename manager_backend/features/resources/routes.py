from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...dependencies import get_session
from .schemas import ResourceSnapshot, RuntimeSessionRecord
from . import service


router = APIRouter(tags=["resources"])
SessionDependency = Annotated[Session, Depends(get_session)]


@router.get("/resources", response_model=ResourceSnapshot, operation_id="resources_snapshot")
def get_resources(session: SessionDependency) -> ResourceSnapshot:
    return service.build_snapshot(session)


@router.get(
    "/sessions",
    response_model=list[RuntimeSessionRecord],
    operation_id="sessions_list",
)
def list_sessions(
    session: SessionDependency,
    limit: int = Query(25, ge=1, le=200),
) -> list[RuntimeSessionRecord]:
    return service.list_sessions(session, limit=limit)
