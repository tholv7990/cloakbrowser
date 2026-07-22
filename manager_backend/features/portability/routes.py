from __future__ import annotations

import re
import unicodedata
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ...dependencies import get_session
from ...errors import ManagerError
from ...schemas.common import ErrorEnvelope
from .profiles import export_profile, import_profile
from .schemas import MAX_PROFILE_DOCUMENT_BYTES, ProfileExportV1, ProfileImportResult


SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter()
MAX_PROFILE_VALIDATION_ERRORS = 16
_SAFE_LOCATION_PARTS = {
    "format",
    "version",
    "exported_at",
    "profile",
    "extensions",
    "name",
    "folder",
    "workflow_status",
    "tags",
    "color",
    "notes",
    "pinned",
    "startup_urls",
    "fingerprint_preset",
    "browser_version_mode",
    "browser_version",
    "user_agent_mode",
    "custom_user_agent",
    "location",
    "window",
    "behavior",
    "proxy",
    "test_proxy_before_launch",
    "permissions",
    "scheme",
    "host",
    "port",
    "mode",
    "width",
    "height",
    "manifest_version",
    "manifest_hash",
}


def _safe_filename(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    slug = slug[:60].rstrip("-") or "profile"
    return f"cloakbrowser-profile-{slug}.json"


def _validation_fields(error: ValidationError) -> dict[str, str]:
    fields: dict[str, str] = {}
    for item in error.errors()[:MAX_PROFILE_VALIDATION_ERRORS]:
        parts: list[str] = []
        for part in item.get("loc", ())[:6]:
            if isinstance(part, int):
                safe = "item"
            elif part in _SAFE_LOCATION_PARTS:
                safe = part
            elif parts and parts[-1] == "permissions":
                safe = "key"
            else:
                safe = "field"
            if not parts or parts[-1] != safe:
                parts.append(safe)
        field = ".".join(parts) if parts else "document"
        fields.setdefault(field, "invalid")
    return fields


@router.get(
    "/profiles/{profile_id}/export",
    response_class=Response,
    responses={404: {"model": ErrorEnvelope, "description": "Profile not found"}},
)
def download_profile(profile_id: str, session: SessionDependency) -> Response:
    warning_codes: list[str] = []
    document = export_profile(session, profile_id, warning_codes=warning_codes)
    filename = _safe_filename(document.profile.name)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if warning_codes:
        headers["X-CloakBrowser-Export-Warning"] = ",".join(warning_codes)
    return Response(
        content=document.model_dump_json().encode("utf-8"),
        media_type="application/json",
        headers=headers,
    )


@router.post(
    "/profiles/import",
    response_model=ProfileImportResult,
    status_code=status.HTTP_201_CREATED,
    responses={
        413: {"model": ErrorEnvelope, "description": "Profile document too large"},
    },
)
async def upload_profile(request: Request, session: SessionDependency) -> ProfileImportResult:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = 0
        if declared_length > MAX_PROFILE_DOCUMENT_BYTES:
            raise ManagerError(
                "profile_document_too_large",
                "Profile documents may not exceed 2 MiB.",
                413,
                {"document": "too_large"},
            )

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_PROFILE_DOCUMENT_BYTES:
            raise ManagerError(
                "profile_document_too_large",
                "Profile documents may not exceed 2 MiB.",
                413,
                {"document": "too_large"},
            )
        body.extend(chunk)
    try:
        document = ProfileExportV1.model_validate_json(bytes(body))
    except ValidationError as error:
        raise ManagerError(
            "invalid_profile_document",
            "The profile document is invalid or unsupported.",
            422,
            _validation_fields(error),
        ) from None
    return import_profile(session, request.app.state.settings, document)
