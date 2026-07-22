from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from ...dependencies import get_session
from .schemas import (
    DiagnosticKind,
    DiagnosticPage,
    DiagnosticRead,
    DiagnosticStatus,
    ProfileDiagnosticRequest,
)
from .service import diagnostic_to_dict, get_diagnostic, list_diagnostics
from .artifacts import ArtifactNotFound, ArtifactUnavailable, read_diagnostic_artifact
from ...errors import ManagerError


router = APIRouter()
SessionDependency = Annotated[Session, Depends(get_session)]


def _serialize(request: Request, run):
    return diagnostic_to_dict(run, request.app.state.settings.data_root)


@router.get("/diagnostics", response_model=DiagnosticPage)
def diagnostics(
    request: Request,
    session: SessionDependency,
    profile: str | None = Query(default=None, min_length=1, max_length=36),
    kind: DiagnosticKind | None = None,
    status_filter: DiagnosticStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    items, total, pages = list_diagnostics(
        session,
        profile_id=profile,
        kind=kind,
        status=status_filter,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [_serialize(request, item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


def _create(request: Request, kind: DiagnosticKind, profile_id: str | None):
    run = request.app.state.diagnostic_manager.create(kind, profile_id)
    return _serialize(request, run)


@router.post(
    "/diagnostics/direct-google-control",
    response_model=DiagnosticRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_direct_google_control(request: Request):
    return _create(request, "direct_google_control", None)


@router.post(
    "/diagnostics/pixelscan",
    response_model=DiagnosticRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_pixelscan(payload: ProfileDiagnosticRequest, request: Request):
    return _create(request, "pixelscan", payload.profile_id)


@router.post(
    "/diagnostics/iphey",
    response_model=DiagnosticRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_iphey(payload: ProfileDiagnosticRequest, request: Request):
    return _create(request, "iphey", payload.profile_id)


@router.post(
    "/diagnostics/cloudflare",
    response_model=DiagnosticRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_cloudflare(payload: ProfileDiagnosticRequest, request: Request):
    return _create(request, "cloudflare", payload.profile_id)


@router.post(
    "/diagnostics/google-search",
    response_model=DiagnosticRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_google_search(payload: ProfileDiagnosticRequest, request: Request):
    return _create(request, "google_search", payload.profile_id)


@router.get("/diagnostics/{diagnostic_id}", response_model=DiagnosticRead)
def diagnostic(diagnostic_id: str, request: Request, session: SessionDependency):
    return _serialize(request, get_diagnostic(session, diagnostic_id))


def _artifact(
    diagnostic_id: str,
    kind: str,
    request: Request,
    session: Session,
) -> Response:
    run = get_diagnostic(session, diagnostic_id)
    settings = request.app.state.settings
    persisted_path = run.report_path if kind == "report" else run.screenshot_path
    maximum = (
        settings.diagnostic_max_report_bytes
        if kind == "report"
        else settings.diagnostic_max_screenshot_bytes
    )
    try:
        artifact = read_diagnostic_artifact(
            settings.data_root,
            run.id,
            kind,
            persisted_path,
            max_bytes=maximum,
        )
    except ArtifactNotFound:
        raise ManagerError(
            "diagnostic_artifact_not_found",
            "The diagnostic artifact was not found.",
            404,
        ) from None
    except ArtifactUnavailable:
        raise ManagerError(
            "diagnostic_artifact_unavailable",
            "The diagnostic artifact cannot be served safely.",
            409,
        ) from None
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": (
                f'{artifact.disposition}; filename="{artifact.filename}"'
            ),
        },
    )


@router.get("/diagnostics/{diagnostic_id}/artifacts/report")
def report_artifact(
    diagnostic_id: str, request: Request, session: SessionDependency
):
    return _artifact(diagnostic_id, "report", request, session)


@router.get("/diagnostics/{diagnostic_id}/artifacts/screenshot")
def screenshot_artifact(
    diagnostic_id: str, request: Request, session: SessionDependency
):
    return _artifact(diagnostic_id, "screenshot", request, session)


@router.post("/diagnostics/{diagnostic_id}/cancel", response_model=DiagnosticRead)
async def cancel_diagnostic(diagnostic_id: str, request: Request):
    executor = request.app.state.diagnostic_executor
    if executor is None:
        run = request.app.state.diagnostic_manager.cancel(diagnostic_id)
    else:
        run = await executor.cancel(diagnostic_id)
    return _serialize(request, run)
