from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@dataclass(slots=True)
class ManagerError(Exception):
    code: str
    message: str
    status_code: int
    field_errors: dict[str, Any] = field(default_factory=dict)


def error_payload(error: ManagerError, request_id: str | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": error.code,
            "message": error.message,
            "field_errors": error.field_errors,
            "request_id": request_id or str(uuid4()),
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ManagerError)
    async def handle_manager_error(request: Request, error: ManagerError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=error.status_code,
            content=error_payload(error, request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        field_errors: dict[str, str] = {}
        for item in error.errors():
            location = [str(part) for part in item.get("loc", ()) if part != "body"]
            field = ".".join(location) or "request"
            field_errors.setdefault(field, str(item.get("msg", "Invalid value")))
        safe_error = ManagerError(
            "validation_error",
            "One or more request fields are invalid.",
            422,
            field_errors,
        )
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=422,
            content=error_payload(safe_error, request_id),
        )
