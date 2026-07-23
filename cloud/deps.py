"""Per-request dependencies: DB session (commit-on-success), settings, and the
authenticated access-token identity."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Header, Request
from sqlalchemy.orm import Session

from .config import CloudSettings
from .db import utc_now
from .entitlements import EntitlementError
from .errors import CloudError
from .tokens import verify_access_token


def get_settings(request: Request) -> CloudSettings:
    return request.app.state.settings


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def require_access(
    request: Request, authorization: str | None = Header(default=None)
) -> dict:
    """Validate the Bearer access token and return its claims (sub, sid, device_id)."""
    settings: CloudSettings = request.app.state.settings
    if not authorization or not authorization.startswith("Bearer "):
        raise CloudError("unauthorized")
    token = authorization[len("Bearer ") :]
    try:
        claims = verify_access_token(token, settings.signing_public_key)
    except EntitlementError as error:
        raise CloudError("unauthorized") from error
    if int(claims.get("exp", 0)) <= int(utc_now().timestamp()):
        raise CloudError("token_expired")
    return claims
