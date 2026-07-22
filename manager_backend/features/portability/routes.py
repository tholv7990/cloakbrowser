from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException

from ...dependencies import get_session
from ...errors import ManagerError
from ...schemas.common import ErrorEnvelope
from ..profiles.service import get_profile
from ..proxies.service import resolve_proxy_url
from .browser_cookies import CookieProfileConfig
from .cookies import MAX_COOKIE_PAYLOAD_BYTES, parse_cookie_payload, to_netscape
from .profiles import export_profile, import_profile
from .schemas import (
    MAX_PROFILE_DOCUMENT_BYTES,
    CookieImportResult,
    ProfileExportV1,
    ProfileImportResult,
)


SessionDependency = Annotated[Session, Depends(get_session)]
router = APIRouter()
MAX_PROFILE_VALIDATION_ERRORS = 16
_COOKIE_OPERATION_TASKS: set[asyncio.Task[Any]] = set()
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


def _safe_cookie_filename(name: str, suffix: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    slug = slug[:60].rstrip("-") or "profile"
    return f"cloakbrowser-cookies-{slug}.{suffix}"


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


async def _bounded_cookie_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = 0
        if declared_length > MAX_COOKIE_PAYLOAD_BYTES:
            raise ManagerError(
                "cookie_payload_too_large",
                "Cookie imports may not exceed 10 MiB.",
                413,
                {"document": "too_large"},
            )
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_COOKIE_PAYLOAD_BYTES:
            raise ManagerError(
                "cookie_payload_too_large",
                "Cookie imports may not exceed 10 MiB.",
                413,
                {"document": "too_large"},
            )
        body.extend(chunk)
    return bytes(body)


def _invalid_cookie_document() -> ManagerError:
    return ManagerError(
        "invalid_cookie_document",
        "The cookie import document is invalid or unsupported.",
        422,
        {"document": "invalid"},
    )


async def _cookie_request_parts(
    request: Request, body: bytes
) -> tuple[str | None, object]:
    content_type = request.headers.get("content-type", "")
    base_media_type = content_type.partition(";")[0].strip().casefold()
    if base_media_type == "application/json":
        return None, body

    if base_media_type == "multipart/form-data":
        delivered = False
        _base, separator, parameters = content_type.partition(";")
        normalized_content_type = "multipart/form-data"
        if separator:
            normalized_content_type += f";{parameters}"

        async def receive() -> dict[str, object]:
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        scope = dict(request.scope)
        scope["headers"] = [
            (
                key,
                normalized_content_type.encode("latin-1")
                if key.lower() == b"content-type"
                else value,
            )
            for key, value in request.scope["headers"]
        ]
        buffered = Request(scope, receive=receive)
        try:
            async with buffered.form(
                max_files=1,
                max_fields=1,
                max_part_size=MAX_COOKIE_PAYLOAD_BYTES,
            ) as form:
                items = list(form.multi_items())
                if len(items) != 2 or {key for key, _value in items} != {"format", "file"}:
                    raise _invalid_cookie_document()
                format = form.get("format")
                upload = form.get("file")
                if not isinstance(format, str) or not isinstance(upload, UploadFile):
                    raise _invalid_cookie_document()
                content = await upload.read()
        except MultiPartException:
            raise _invalid_cookie_document() from None
        return format, content

    raise _invalid_cookie_document()


def _json_cookie_request_parts(body: object) -> tuple[str, str]:
    try:
        document = json.loads(body)
    except (TypeError, ValueError):
        raise ValueError("invalid_cookie_document") from None
    if not isinstance(document, dict) or set(document) != {"format", "content"}:
        raise ValueError("invalid_cookie_document")
    format = document.get("format")
    content = document.get("content")
    if not isinstance(format, str) or not isinstance(content, str):
        raise ValueError("invalid_cookie_document")
    return format, content


def _prepared_cookie_profile(
    request: Request, session: Session, profile_id: str
) -> tuple[object, CookieProfileConfig]:
    profile = _stopped_profile(session, profile_id)
    proxy_url = None
    if profile.proxy_id is not None:
        proxy_url = resolve_proxy_url(
            session, request.app.state.credential_store, profile.proxy_id
        )
    config = CookieProfileConfig.from_profile(
        profile,
        request.app.state.settings,
        proxy_url=proxy_url,
    )
    return profile, config


def _parse_and_import_cookies(
    adapter: object,
    profile_config: CookieProfileConfig,
    format: str | None,
    content: object,
):
    if format is None:
        format, content = _json_cookie_request_parts(content)
    if format not in {"json", "playwright", "netscape"}:
        raise ValueError("invalid_cookie_document")
    parsed = parse_cookie_payload(content, format)
    adapter.import_cookies(profile_config, parsed.cookies)
    return (
        format,
        len(parsed.cookies),
        parsed.skipped,
        parsed.rejected,
        [warning.model_dump() for warning in parsed.warnings],
    )


def _release_cookie_operation(task: asyncio.Task[Any]) -> None:
    _COOKIE_OPERATION_TASKS.discard(task)
    if not task.cancelled():
        task.exception()


async def _run_owned_sync_cookie_operation(operation: Callable[[], Any]) -> Any:
    task = asyncio.create_task(asyncio.to_thread(operation))
    _COOKIE_OPERATION_TASKS.add(task)
    task.add_done_callback(_release_cookie_operation)
    return await asyncio.shield(task)


def _stopped_profile(session: Session, profile_id: str):
    profile = get_profile(session, profile_id)
    if profile.runtime_state != "stopped":
        raise ManagerError(
            "profile_not_stopped",
            "The profile must be stopped for cookie operations.",
            409,
        )
    return profile


def _cookie_operation_failed() -> ManagerError:
    return ManagerError(
        "cookie_operation_failed",
        "The browser cookie operation could not be completed.",
        500,
    )


@router.post(
    "/profiles/{profile_id}/cookies/import",
    response_model=CookieImportResult,
    responses={413: {"model": ErrorEnvelope, "description": "Cookie document too large"}},
)
async def upload_cookies(
    profile_id: str, request: Request, session: SessionDependency
) -> CookieImportResult:
    body = await _bounded_cookie_body(request)
    format, content = await _cookie_request_parts(request, body)
    _profile, profile_config = _prepared_cookie_profile(request, session, profile_id)
    adapter = request.app.state.cookie_context_adapter
    try:
        (
            format,
            imported_count,
            skipped_count,
            rejected_count,
            warnings,
        ) = await _run_owned_sync_cookie_operation(
            lambda: _parse_and_import_cookies(
                adapter,
                profile_config,
                format,
                content,
            )
        )
    except ValueError:
        raise _invalid_cookie_document() from None
    except ManagerError as error:
        if error.code in {"profile_locked", "cookie_operation_failed"}:
            raise
        raise _cookie_operation_failed() from None
    except Exception:
        raise _cookie_operation_failed() from None
    return CookieImportResult.model_validate({
        "format": format,
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "rejected_count": rejected_count,
        "warnings": warnings,
    })


@router.get(
    "/profiles/{profile_id}/cookies/export",
    response_class=Response,
    responses={404: {"model": ErrorEnvelope, "description": "Profile not found"}},
)
def download_cookies(
    profile_id: str,
    request: Request,
    session: SessionDependency,
    format: Literal["playwright", "netscape"] = "playwright",
) -> Response:
    profile, profile_config = _prepared_cookie_profile(request, session, profile_id)
    try:
        cookies = request.app.state.cookie_context_adapter.export_cookies(profile_config)
        if format == "netscape":
            content = to_netscape(cookies).encode("utf-8")
            suffix = "txt"
            media_type = "text/plain"
        else:
            content = (
                json.dumps(cookies, ensure_ascii=False, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            suffix = "json"
            media_type = "application/json"
    except ManagerError as error:
        if error.code in {"profile_locked", "cookie_operation_failed"}:
            raise
        raise _cookie_operation_failed() from None
    except Exception:
        raise _cookie_operation_failed() from None
    filename = _safe_cookie_filename(profile.name, suffix)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
