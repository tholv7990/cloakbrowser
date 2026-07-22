from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from ...dependencies import get_session
from .schemas import (
    CanonicalUuid,
    ExtensionPatch,
    ExtensionRead,
    ExtensionRegister,
    ProfileExtensionAssignment,
    ProfileExtensionAssignmentRead,
)
from .service import (
    extension_to_dict,
    get_extension,
    list_extensions,
    register_extension,
    set_profile_extensions,
    unregister_extension,
    update_extension,
)


router = APIRouter()
SessionDependency = Annotated[Session, Depends(get_session)]


@router.get("/extensions", response_model=list[ExtensionRead])
def list_all(session: SessionDependency):
    return [extension_to_dict(item) for item in list_extensions(session)]


@router.post(
    "/extensions", response_model=ExtensionRead, status_code=status.HTTP_201_CREATED
)
def register(
    payload: ExtensionRegister,
    request: Request,
    response: Response,
    session: SessionDependency,
):
    extension, created = register_extension(
        session, request.app.state.settings, payload.directory
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return extension_to_dict(extension)


@router.get("/extensions/{extension_id}", response_model=ExtensionRead)
def get(extension_id: CanonicalUuid, session: SessionDependency):
    return extension_to_dict(get_extension(session, extension_id))


@router.patch("/extensions/{extension_id}", response_model=ExtensionRead)
def patch(
    extension_id: CanonicalUuid,
    payload: ExtensionPatch,
    request: Request,
    session: SessionDependency,
):
    extension = update_extension(
        session,
        request.app.state.settings,
        extension_id,
        enabled=payload.enabled,
        refresh=payload.refresh,
    )
    return extension_to_dict(extension)


@router.delete("/extensions/{extension_id}", status_code=status.HTTP_204_NO_CONTENT)
def unregister(extension_id: CanonicalUuid, session: SessionDependency) -> Response:
    unregister_extension(session, extension_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/profiles/{profile_id}/extensions",
    response_model=ProfileExtensionAssignmentRead,
)
def assign(
    profile_id: CanonicalUuid,
    payload: ProfileExtensionAssignment,
    session: SessionDependency,
):
    assigned = set_profile_extensions(session, profile_id, payload.extension_ids)
    return {"extension_ids": [extension.id for extension in assigned]}
