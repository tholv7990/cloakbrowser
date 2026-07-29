"""HTTP surface for the Shop email phone-OTP check feature.

All routes inherit the shared /api/v1 session/origin/CSRF/local-token auth from
the parent api_router. Mutating "start work" endpoints add the maintenance gate.
The create payload's email text is write-only and never echoed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ...dependencies import get_session
from ...maintenance import guard_maintenance
from . import service
from .schemas import (
    EmailResult,
    ShopCheckEmailPage,
    ShopCheckRunCreate,
    ShopCheckRunCreateResult,
    ShopCheckRunDetail,
    ShopCheckRunPage,
)


router = APIRouter(prefix="/automations/shop-check", tags=["shop_check"])
SessionDependency = Annotated[Session, Depends(get_session)]


@router.post(
    "/runs",
    response_model=ShopCheckRunCreateResult,
    status_code=202,
    operation_id="shop_check_runs_create",
    dependencies=[Depends(guard_maintenance)],
)
def create_run(payload: ShopCheckRunCreate, request: Request, session: SessionDependency):
    return service.create_run(
        session,
        request.app.state.credential_store,
        payload,
        request.app.state.session_factory,
    )


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
    "/runs/{run_id}/cancel",
    response_model=ShopCheckRunDetail,
    operation_id="shop_check_runs_cancel",
)
def cancel_run(run_id: str, request: Request, session: SessionDependency):
    # Route through the coordinator so a live run's workers get the cancel signal;
    # the persisted status is the source of truth either way.
    return request.app.state.shop_check_coordinator.cancel(session, run_id)
