from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from .schemas import BackupArchiveRead
from .service import create_backup, delete_backup, list_backups, restore_backup


router = APIRouter(prefix="/backups", tags=["backups"])


@router.get("", response_model=list[BackupArchiveRead], operation_id="backups_list")
def list_route(request: Request):
    return list_backups(request.app.state.settings.data_root)


@router.post(
    "",
    response_model=BackupArchiveRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="backups_create",
)
def create_route(request: Request):
    return create_backup(
        request.app.state.engine, request.app.state.settings.data_root, automatic=False
    )


@router.post(
    "/{backup_id}/restore",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="backups_restore",
)
def restore_route(backup_id: str, request: Request) -> Response:
    # Exclusive: rejects concurrent worker-spawning / state-changing operations and
    # drains any in-flight ones before rewriting the database in place.
    with request.app.state.maintenance_gate.exclusive():
        restore_backup(
            request.app.state.engine, request.app.state.settings.data_root, backup_id
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{backup_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="backups_delete",
)
def delete_route(backup_id: str, request: Request) -> Response:
    delete_backup(request.app.state.settings.data_root, backup_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
