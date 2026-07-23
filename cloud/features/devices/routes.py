"""Device HTTP routes: list the caller's devices, revoke one."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ... import models
from ...deps import get_session, require_access
from ...errors import CloudError
from ...schemas import DeviceResponse, MessageResponse
from . import service as devices

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", response_model=list[DeviceResponse])
def list_devices(
    claims: dict = Depends(require_access), session: Session = Depends(get_session)
) -> list[DeviceResponse]:
    return [
        DeviceResponse(
            id=device.id,
            name=device.name,
            platform=device.platform,
            revoked=device.revoked_at is not None,
        )
        for device in devices.list_devices(session, user_id=claims["sub"])
    ]


@router.post("/{device_id}/revoke", response_model=MessageResponse)
def revoke(
    device_id: str,
    claims: dict = Depends(require_access),
    session: Session = Depends(get_session),
) -> MessageResponse:
    device = session.get(models.Device, device_id)
    # Never reveal another account's devices — a foreign/unknown id is "not found".
    if device is None or device.user_id != claims["sub"]:
        raise CloudError("not_found")
    devices.revoke_device(session, device_id=device_id)
    return MessageResponse(status="revoked")
