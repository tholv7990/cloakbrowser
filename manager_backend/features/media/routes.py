from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ...dependencies import get_session
from .schemas import (
    MediaAssetCreate,
    MediaAssetRead,
    MediaAssignmentsWrite,
    MediaSettingsPatch,
    MediaSettingsRead,
)
from .service import (
    create_asset,
    delete_asset,
    get_assignments,
    get_settings,
    list_assets,
    set_assignments,
    update_settings,
)


router = APIRouter(prefix="/media", tags=["media"])
SessionDependency = Annotated[Session, Depends(get_session)]


@router.get("/settings", response_model=MediaSettingsRead, operation_id="media_settings_get")
def get_settings_route(session: SessionDependency):
    return get_settings(session)


@router.patch("/settings", response_model=MediaSettingsRead, operation_id="media_settings_update")
def patch_settings_route(payload: MediaSettingsPatch, session: SessionDependency):
    return update_settings(session, enabled=payload.enabled)


@router.get("/assets", response_model=list[MediaAssetRead], operation_id="media_assets_list")
def list_assets_route(session: SessionDependency):
    return list_assets(session)


@router.post(
    "/assets",
    response_model=MediaAssetRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="media_assets_create",
)
def create_asset_route(payload: MediaAssetCreate, session: SessionDependency):
    return create_asset(
        session, name=payload.name, kind=payload.kind, media_format=payload.format
    )


@router.delete(
    "/assets/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="media_assets_delete",
)
def delete_asset_route(asset_id: str, session: SessionDependency) -> Response:
    delete_asset(session, asset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/assets/{asset_id}/assignments",
    response_model=list[str],
    operation_id="media_assignments_get",
)
def get_assignments_route(asset_id: str, session: SessionDependency):
    return get_assignments(session, asset_id)


@router.put(
    "/assets/{asset_id}/assignments",
    response_model=MediaAssetRead,
    operation_id="media_assignments_set",
)
def set_assignments_route(
    asset_id: str, payload: MediaAssignmentsWrite, session: SessionDependency
):
    return set_assignments(session, asset_id, payload.profile_ids)
