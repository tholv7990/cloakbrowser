"""Update HTTP route: the latest signed release for a channel (public)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ...deps import get_session
from ...errors import CloudError
from ...schemas import UpdateReleaseResponse
from . import service as updates

router = APIRouter(tags=["updates"])


@router.get("/updates/latest", response_model=UpdateReleaseResponse)
def latest(
    channel: str = "stable", session: Session = Depends(get_session)
) -> UpdateReleaseResponse:
    if channel not in updates.CHANNELS:
        raise CloudError("not_found")
    release = updates.get_latest_release(session, channel=channel)
    if release is None:
        raise CloudError("not_found")
    return UpdateReleaseResponse(
        channel=release.channel,
        version=release.version,
        min_supported_version=release.min_supported_version,
        artifact_url=release.artifact_url,
        sha256=release.sha256,
        signature=release.signature,
        published_at=release.published_at,
    )


@router.get("/updates/tauri/{target}/{current_version}")
def tauri_update(
    target: str,
    current_version: str,
    channel: str = "stable",
    session: Session = Depends(get_session),
):
    """Tauri v2 dynamic-update endpoint. 204 = up to date; 200 = a newer release's
    signed manifest. `target` (e.g. windows-x86_64) is accepted for the Tauri
    contract; v1 ships one artifact per channel."""
    if channel not in updates.CHANNELS:
        return Response(status_code=204)
    release = updates.get_latest_release(session, channel=channel)
    if release is None or not updates.is_newer(release.version, current_version):
        return Response(status_code=204)
    return updates.tauri_manifest(release)
