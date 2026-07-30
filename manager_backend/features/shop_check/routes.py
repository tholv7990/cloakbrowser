"""HTTP surface for the Shop email phone-OTP check feature.

All routes inherit the shared /api/v1 session/origin/CSRF/local-token auth from
the parent api_router. Mutating "start work" endpoints add the maintenance gate.
The create payload's email text is write-only and never echoed.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ...dependencies import get_session
from ...maintenance import guard_maintenance
from . import service
from .cleanup import cleanup_run
from .export import export_run
from .sanitize import sanitize_error
from .schemas import (
    EmailResult,
    ShopCheckCleanupRequest,
    ShopCheckCleanupResult,
    ShopCheckEmailPage,
    ShopCheckExportResult,
    ShopCheckRunCreate,
    ShopCheckRunCreateResult,
    ShopCheckRunDetail,
    ShopCheckRunPage,
)


router = APIRouter(prefix="/automations/shop-check", tags=["shop_check"])
SessionDependency = Annotated[Session, Depends(get_session)]
_logger = logging.getLogger(__name__)


@router.post(
    "/runs",
    response_model=ShopCheckRunCreateResult,
    status_code=202,
    operation_id="shop_check_runs_create",
    dependencies=[Depends(guard_maintenance)],
)
def create_run(payload: ShopCheckRunCreate, request: Request, session: SessionDependency):
    result = service.create_run(
        session,
        request.app.state.credential_store,
        payload,
        request.app.state.session_factory,
    )
    run_id = result["run"]["id"]
    # 202 means accepted AND started: hand the queued run to the coordinator,
    # which claims it here and provisions on its own threads.
    try:
        result["run"] = request.app.state.shop_check_coordinator.start(session, run_id)
    except Exception as error:
        # The run already committed, so never turn a failed hand-off into a 500 —
        # that invites a duplicate-run retry (double provisioning). The run stays
        # visible and cancellable. Log a sanitized reason, never the input.
        _logger.warning(
            "shop_check: coordinator hand-off failed for run %s: %s",
            run_id,
            sanitize_error(error),
        )
    return result


@router.get(
    "/runs",
    response_model=ShopCheckRunPage,
    operation_id="shop_check_runs_list",
)
def list_runs(
    session: SessionDependency,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
):
    return service.list_runs(session, page=page, page_size=page_size)


@router.get(
    "/runs/{run_id}",
    response_model=ShopCheckRunDetail,
    operation_id="shop_check_runs_get",
)
def get_run(run_id: str, session: SessionDependency):
    return service.get_run_detail(session, run_id)


@router.get(
    "/runs/{run_id}/emails",
    response_model=ShopCheckEmailPage,
    operation_id="shop_check_runs_emails",
)
def list_emails(
    run_id: str,
    session: SessionDependency,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    result: EmailResult | None = Query(default=None),
):
    return service.list_emails(
        session, run_id, page=page, page_size=page_size, result=result
    )


@router.post(
    "/runs/{run_id}/export",
    response_model=ShopCheckExportResult,
    operation_id="shop_check_runs_export",
)
def export_run_results(run_id: str, request: Request, session: SessionDependency):
    # Writes results.csv (masked) + matched.txt (plaintext deliverable) under the
    # app export root. The response carries only paths + counts, never an address.
    return export_run(
        session,
        request.app.state.credential_store,
        request.app.state.settings,
        run_id,
    )


@router.post(
    "/runs/{run_id}/cancel",
    response_model=ShopCheckRunDetail,
    operation_id="shop_check_runs_cancel",
)
def cancel_run(run_id: str, request: Request, session: SessionDependency):
    # Route through the coordinator so a live run's workers get the cancel signal;
    # the persisted status is the source of truth either way.
    return request.app.state.shop_check_coordinator.cancel(session, run_id)


@router.post(
    "/runs/{run_id}/cleanup",
    response_model=ShopCheckCleanupResult,
    operation_id="shop_check_runs_cleanup",
    dependencies=[Depends(guard_maintenance)],
)
def cleanup_run_profiles(
    run_id: str,
    payload: ShopCheckCleanupRequest,
    request: Request,
    session: SessionDependency,
):
    # Hard-deletes ONLY this run's owned profiles (from immutable provenance),
    # stopping their runtimes first. run_id comes from the path; the client
    # supplies no ids or paths, only the count it saw (guards a stale UI).
    return cleanup_run(
        session,
        request.app.state.settings,
        request.app.state.runtime_manager,
        run_id,
        expected_profile_count=payload.expected_profile_count,
    )
