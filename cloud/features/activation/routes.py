"""Activation HTTP routes: redeem a key, refresh the entitlement. Both bind to the
device in the caller's access token — no device id is trusted from the body."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ... import audit, licensing
from ...config import CloudSettings
from ...deps import get_session, get_settings, require_access
from ...errors import CloudError
from ...schemas import EntitlementResponse, RedeemRequest

router = APIRouter(tags=["activation"])


@router.post("/activation/redeem", response_model=EntitlementResponse)
def redeem(
    body: RedeemRequest,
    claims: dict = Depends(require_access),
    session: Session = Depends(get_session),
    settings: CloudSettings = Depends(get_settings),
) -> EntitlementResponse:
    try:
        result = licensing.redeem_key(
            session,
            raw_key=body.activation_key,
            user_id=claims["sub"],
            device_id=claims["device_id"],
            pepper=settings.activation_pepper,
            private_key=settings.signing_private_key,
            ttl=settings.entitlement_ttl,
            grace=settings.offline_grace,
        )
    except licensing.RedeemError as error:
        raise CloudError(error.code) from error
    if not result.reused:
        # Log the use actually consumed (idempotent re-issues aren't a new consumption).
        audit.record(
            session,
            actor=claims["sub"],
            action="activation.redeem",
            subject_type="activation_key",
            subject_id=result.entitlement.key_id,
            data={"device_id": claims["device_id"], "plan": result.entitlement.plan_id},
        )
    return EntitlementResponse(entitlement_token=result.token)


@router.post("/entitlement/refresh", response_model=EntitlementResponse)
def entitlement_refresh(
    claims: dict = Depends(require_access),
    session: Session = Depends(get_session),
    settings: CloudSettings = Depends(get_settings),
) -> EntitlementResponse:
    try:
        result = licensing.refresh_entitlement(
            session,
            device_id=claims["device_id"],
            private_key=settings.signing_private_key,
            ttl=settings.entitlement_ttl,
            grace=settings.offline_grace,
        )
    except licensing.RefreshError as error:
        raise CloudError(error.code) from error
    return EntitlementResponse(entitlement_token=result.token)
