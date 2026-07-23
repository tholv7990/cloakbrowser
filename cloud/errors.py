"""Uniform, safe error responses. Bodies are a fixed ``{"error": <code>}`` — no
secret, no internal detail leaks. Service-layer codes map to HTTP status here."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Service error code -> HTTP status.
STATUS: dict[str, int] = {
    # auth
    "email_taken": 409,
    "invalid_token": 400,
    "invalid_credentials": 401,
    "account_unverified": 403,
    "account_suspended": 403,
    "invalid_refresh": 401,
    "refresh_reuse": 401,
    "refresh_expired": 401,
    "device_mismatch": 403,
    "invalid_grant": 400,
    "invalid_request": 400,
    # devices
    "bad_signature": 401,
    "device_revoked": 403,
    "device_cap": 409,
    # licensing
    "invalid_key": 404,
    "key_suspended": 403,
    "key_revoked": 403,
    "key_expired": 403,
    "key_exhausted": 409,
    "plan_missing": 500,
    "redeem_conflict": 409,
    "not_entitled": 403,
    # transport / auth surface
    "unauthorized": 401,
    "token_expired": 401,
    "throttled": 429,
    "not_found": 404,
}


class CloudError(Exception):
    def __init__(self, code: str, status_code: int | None = None):
        self.code = code
        self.status_code = status_code or STATUS.get(code, 400)
        super().__init__(code)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(CloudError)
    async def _cloud_error(_request: Request, exc: CloudError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.code})
