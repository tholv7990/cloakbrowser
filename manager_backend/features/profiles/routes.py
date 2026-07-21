from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ...dependencies import get_session
from ...errors import ManagerError
from .schemas import (
    BulkProfileRequest,
    BulkProfileResult,
    ProfileCreate,
    ProfilePage,
    ProfilePatch,
    ProfileRead,
)
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


@router.get("/profiles", response_model=ProfilePage)
def profiles(
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
    )


@router.post("/profiles", response_model=ProfileRead, status_code=status.HTTP_201_CREATED)
def create(payload: ProfileCreate, session: SessionDependency):
    return profile_to_dict(create_profile(session, payload))


@router.post(
    "/profiles/quick-create",
    response_model=ProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def quick_create(payload: ProfileCreate, session: SessionDependency):
    return profile_to_dict(create_profile(session, payload))


@router.post("/profiles/bulk", response_model=BulkProfileResult)
def bulk(payload: BulkProfileRequest, session: SessionDependency):
    ids, count = bulk_update(session, payload)
    return {"updated_ids": ids, "count": count}


@router.get("/profiles/{profile_id}", response_model=ProfileRead)
def get(profile_id: str, session: SessionDependency):
    return profile_to_dict(get_profile(session, profile_id))


@router.patch("/profiles/{profile_id}", response_model=ProfileRead)
def patch(profile_id: str, payload: ProfilePatch, session: SessionDependency):
    return profile_to_dict(update_profile(session, profile_id, payload))


@router.post(
    "/profiles/{profile_id}/duplicate",
    response_model=ProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def duplicate(profile_id: str, session: SessionDependency):
    return profile_to_dict(duplicate_profile(session, profile_id))


@router.post("/profiles/{profile_id}/regenerate-fingerprint", response_model=ProfileRead)
def regenerate(profile_id: str, session: SessionDependency):
    return profile_to_dict(regenerate_fingerprint(session, profile_id))


@router.post("/profiles/{profile_id}/move-to-trash", response_model=ProfileRead)
def move_to_trash(profile_id: str, session: SessionDependency):
    return profile_to_dict(set_trash_state(session, profile_id, True))


@router.post("/profiles/{profile_id}/restore", response_model=ProfileRead)
def restore(profile_id: str, session: SessionDependency):
    return profile_to_dict(set_trash_state(session, profile_id, False))


def _runtime_not_available(session: Session, profile_id: str) -> None:
    get_profile(session, profile_id)
    raise ManagerError(
        "runtime_not_available",
        "The browser runtime service is not installed yet.",
        501,
    )


@router.post("/profiles/{profile_id}/start")
def start(profile_id: str, session: SessionDependency):
    _runtime_not_available(session, profile_id)


@router.post("/profiles/{profile_id}/stop")
def stop(profile_id: str, session: SessionDependency):
    _runtime_not_available(session, profile_id)


@router.post("/profiles/{profile_id}/focus-window")
def focus_window(profile_id: str, session: SessionDependency):
    _runtime_not_available(session, profile_id)
