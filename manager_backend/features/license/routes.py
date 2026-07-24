"""License routes: report status for the UI, install a fresh entitlement, deactivate.

The raw entitlement token is never returned — only derived, non-secret status.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from . import service
from .schemas import InstallEntitlementRequest, LicenseStatusRead

router = APIRouter(prefix="/license", tags=["license"])


@router.get("", response_model=LicenseStatusRead, operation_id="license_status")
def license_status(request: Request) -> LicenseStatusRead:
    return LicenseStatusRead.of(service.evaluate_license(request.app.state.settings))


@router.post("/entitlement", response_model=LicenseStatusRead, operation_id="license_install")
def install_entitlement(
    request: Request, payload: InstallEntitlementRequest
) -> LicenseStatusRead:
    status = service.install_entitlement(
        request.app.state.settings, payload.entitlement_token
    )
    return LicenseStatusRead.of(status)


@router.delete("", response_model=LicenseStatusRead, operation_id="license_deactivate")
def deactivate(request: Request) -> LicenseStatusRead:
    service.clear_entitlement(request.app.state.settings)
    return LicenseStatusRead.of(service.evaluate_license(request.app.state.settings))
