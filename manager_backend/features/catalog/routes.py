from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ...dependencies import get_session
from ...models import Folder, Tag, WorkflowStatus
from .schemas import (
    FolderCreate,
    FolderPatch,
    FolderRead,
    ReorderRequest,
    TagCreate,
    TagPatch,
    TagRead,
    WorkflowStatusCreate,
    WorkflowStatusPatch,
    WorkflowStatusRead,
)
from .service import (
    create_catalog,
    delete_catalog,
    list_catalog,
    reorder_catalog,
    update_catalog,
)


SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter()


@router.get("/folders", response_model=list[FolderRead])
def list_folders(session: SessionDependency):
    return list_catalog(session, Folder)


@router.post("/folders", response_model=FolderRead, status_code=status.HTTP_201_CREATED)
def create_folder(payload: FolderCreate, session: SessionDependency):
    return create_catalog(session, Folder, payload.model_dump())


@router.post("/folders/reorder", response_model=list[FolderRead])
def reorder_folders(payload: ReorderRequest, session: SessionDependency):
    return reorder_catalog(session, Folder, payload.ids)


@router.patch("/folders/{item_id}", response_model=FolderRead)
def update_folder(item_id: str, payload: FolderPatch, session: SessionDependency):
    return update_catalog(session, Folder, item_id, payload.model_dump())


@router.delete("/folders/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(item_id: str, session: SessionDependency) -> Response:
    delete_catalog(session, Folder, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tags", response_model=list[TagRead])
def list_tags(session: SessionDependency):
    return list_catalog(session, Tag)


@router.post("/tags", response_model=TagRead, status_code=status.HTTP_201_CREATED)
def create_tag(payload: TagCreate, session: SessionDependency):
    return create_catalog(session, Tag, payload.model_dump())


@router.patch("/tags/{item_id}", response_model=TagRead)
def update_tag(item_id: str, payload: TagPatch, session: SessionDependency):
    return update_catalog(session, Tag, item_id, payload.model_dump(exclude_none=True))


@router.delete("/tags/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(item_id: str, session: SessionDependency) -> Response:
    delete_catalog(session, Tag, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/workflow-statuses", response_model=list[WorkflowStatusRead])
def list_workflow_statuses(session: SessionDependency):
    return list_catalog(session, WorkflowStatus)


@router.post(
    "/workflow-statuses",
    response_model=WorkflowStatusRead,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_status(payload: WorkflowStatusCreate, session: SessionDependency):
    return create_catalog(session, WorkflowStatus, payload.model_dump())


@router.post("/workflow-statuses/reorder", response_model=list[WorkflowStatusRead])
def reorder_workflow_statuses(payload: ReorderRequest, session: SessionDependency):
    return reorder_catalog(session, WorkflowStatus, payload.ids)


@router.patch("/workflow-statuses/{item_id}", response_model=WorkflowStatusRead)
def update_workflow_status(
    item_id: str, payload: WorkflowStatusPatch, session: SessionDependency
):
    return update_catalog(
        session, WorkflowStatus, item_id, payload.model_dump(exclude_none=True)
    )


@router.delete("/workflow-statuses/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow_status(item_id: str, session: SessionDependency) -> Response:
    delete_catalog(session, WorkflowStatus, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
