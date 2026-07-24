"""Account routes: local endpoints the UI calls to sign in to the cloud, activate a
key, refresh the entitlement, and sign out. Credentials go backend-to-backend; no
token or password is ever returned to the WebView.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..license.schemas import LicenseStatusRead
from .schemas import AccountStatusRead, ActivateRequest, LoginRequest

router = APIRouter(prefix="/account", tags=["account"])


def _service(request: Request):
    return request.app.state.account_service


@router.get("", response_model=AccountStatusRead, operation_id="account_status")
def account_status(request: Request) -> AccountStatusRead:
    return AccountStatusRead.of(_service(request).status())


@router.post("/login", response_model=AccountStatusRead, operation_id="account_login")
def login(request: Request, payload: LoginRequest) -> AccountStatusRead:
    status = _service(request).login(email=str(payload.email), password=payload.password)
    return AccountStatusRead.of(status)


@router.post("/activate", response_model=LicenseStatusRead, operation_id="account_activate")
def activate(request: Request, payload: ActivateRequest) -> LicenseStatusRead:
    return LicenseStatusRead.of(
        _service(request).activate(activation_key=payload.activation_key)
    )


@router.post("/refresh", response_model=LicenseStatusRead, operation_id="account_refresh")
def refresh(request: Request) -> LicenseStatusRead:
    return LicenseStatusRead.of(_service(request).refresh_entitlement())


@router.post("/logout", response_model=AccountStatusRead, operation_id="account_logout")
def logout(request: Request) -> AccountStatusRead:
    return AccountStatusRead.of(_service(request).logout())
