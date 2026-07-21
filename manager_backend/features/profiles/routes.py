from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from ...dependencies import get_session
from ...errors import ManagerError
from ...schemas.common import ErrorEnvelope
from ..runtime.logs import MAX_PROFILE_LOG_PAGE_SIZE, list_profile_logs
from ..runtime.routes import runtime_to_dict
from .schemas import (
    BulkProfileRequest,
    BulkProfileResult,
    ProfileCreate,
    ProfileDirectoryOpen,
    ProfileLogPage,
    ProfilePage,
    ProfilePatch,
    ProfileRead,
)
from .directories import open_profile_directory, resolve_profile_directory
from .service import (
    bulk_update,
    create_profile,
    duplicate_profile,
    get_profile,
    list_profiles,
    profile_to_dict,
    regenerate_fingerprint,
    set_trash_state,
    update_profile,
)


SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter()
_OPEN_DIRECTORY_ERRORS = {
    400: {"model": ErrorEnvelope, "description": "Profile directory rejected"},
    404: {"model": ErrorEnvelope, "description": "Profile not found"},
    500: {"model": ErrorEnvelope, "description": "Directory open failed"},
    501: {"model": ErrorEnvelope, "description": "Directory opening unsupported"},
}


@router.get("/profiles", response_model=ProfilePage)
def profiles(
    request: Request,
    session: SessionDependency,
    query: str | None = Query(default=None, max_length=200),
    folder_id: str | None = None,
    tag_id: str | None = None,
    workflow_status_id: str | None = None,
    pinned: bool | None = None,
    sort: str = "-updated_at",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return list_profiles(
        session,
        query=query,
        folder_id=folder_id,
        tag_id=tag_id,
        workflow_status_id=workflow_status_id,
        pinned=pinned,
        sort=sort,
        page=page,
        page_size=page_size,
        settings=request.app.state.settings,
    )


@router.post("/profiles", response_model=ProfileRead, status_code=status.HTTP_201_CREATED)
def create(payload: ProfileCreate, request: Request, session: SessionDependency):
    return profile_to_dict(create_profile(session, payload), settings=request.app.state.settings)


@router.post(
    "/profiles/quick-create",
    response_model=ProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def quick_create(payload: ProfileCreate, request: Request, session: SessionDependency):
    return profile_to_dict(create_profile(session, payload), settings=request.app.state.settings)


@router.post("/profiles/bulk", response_model=BulkProfileResult)
def bulk(payload: BulkProfileRequest, session: SessionDependency):
    ids, count = bulk_update(session, payload)
    return {"updated_ids": ids, "count": count}


@router.get("/profiles/{profile_id}", response_model=ProfileRead)
def get(profile_id: str, request: Request, session: SessionDependency):
    return profile_to_dict(get_profile(session, profile_id), settings=request.app.state.settings)


@router.post(
    "/profiles/{profile_id}/open-directory",
    response_model=ProfileDirectoryOpen,
    responses=_OPEN_DIRECTORY_ERRORS,
)
def open_directory(profile_id: str, request: Request, session: SessionDependency):
    get_profile(session, profile_id)
    directory = resolve_profile_directory(request.app.state.settings, profile_id)
    open_profile_directory(directory)
    return {"profile_directory": str(directory)}


@router.get("/profiles/{profile_id}/logs", response_model=ProfileLogPage)
def logs(
    profile_id: str,
    session: SessionDependency,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=MAX_PROFILE_LOG_PAGE_SIZE),
):
    get_profile(session, profile_id)
    return list_profile_logs(session, profile_id, page=page, page_size=page_size)


@router.patch(
    "/profiles/{profile_id}",
    response_model=ProfileRead,
    responses={409: {"model": ErrorEnvelope, "description": "Profile update conflict"}},
)
def patch(profile_id: str, payload: ProfilePatch, request: Request, session: SessionDependency):
    profile = update_profile(
        session,
        profile_id,
        payload,
        settings=request.app.state.settings,
    )
    return profile_to_dict(profile, settings=request.app.state.settings)


@router.post(
    "/profiles/{profile_id}/duplicate",
    response_model=ProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def duplicate(profile_id: str, request: Request, session: SessionDependency):
    return profile_to_dict(duplicate_profile(session, profile_id), settings=request.app.state.settings)


@router.post("/profiles/{profile_id}/regenerate-fingerprint", response_model=ProfileRead)
def regenerate(profile_id: str, request: Request, session: SessionDependency):
    return profile_to_dict(regenerate_fingerprint(session, profile_id), settings=request.app.state.settings)


@router.post("/profiles/{profile_id}/move-to-trash", response_model=ProfileRead)
def move_to_trash(profile_id: str, request: Request, session: SessionDependency):
    return profile_to_dict(set_trash_state(session, profile_id, True), settings=request.app.state.settings)


@router.post("/profiles/{profile_id}/restore", response_model=ProfileRead)
def restore(profile_id: str, request: Request, session: SessionDependency):
    return profile_to_dict(set_trash_state(session, profile_id, False), settings=request.app.state.settings)


@router.post("/profiles/{profile_id}/start", status_code=status.HTTP_202_ACCEPTED)
def start(profile_id: str, request: Request):
    return runtime_to_dict(request.app.state.runtime_manager.start(profile_id))


@router.post("/profiles/{profile_id}/stop", status_code=status.HTTP_202_ACCEPTED)
def stop(profile_id: str, request: Request, session: SessionDependency):
    get_profile(session, profile_id)
    runtime = request.app.state.runtime_manager.stop(profile_id)
    if runtime is None:
        return {"profile_id": profile_id, "state": "stopped", "last_message": "stopped"}
    return runtime_to_dict(runtime)


@router.post("/profiles/{profile_id}/focus-window")
def focus_window(profile_id: str, session: SessionDependency):
    get_profile(session, profile_id)
    raise ManagerError(
        "runtime_command_not_supported",
        "This runtime command is not supported yet.",
        501,
    )
