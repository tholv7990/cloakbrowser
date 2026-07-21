from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie, APIKeyHeader
from sqlalchemy.orm import Session

from .auth.sessions import ValidatedSession, validate_session
from .errors import ManagerError


SESSION_COOKIE = "cloak_session"
CSRF_COOKIE = "cloak_csrf"
CSRF_HEADER = "x-csrf-token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SESSION_SCHEME = APIKeyCookie(name=SESSION_COOKIE, auto_error=False, scheme_name="SessionCookie")
_CSRF_SCHEME = APIKeyHeader(name="X-CSRF-Token", auto_error=False, scheme_name="CsrfToken")


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def require_allowed_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin != request.app.state.settings.allowed_origin:
        raise ManagerError("invalid_origin", "This browser origin is not allowed.", 403)


def require_authenticated_session(
    request: Request,
    db: Session = Depends(get_session),
    cookie_token: str | None = Security(_SESSION_SCHEME),
    csrf_token: str | None = Security(_CSRF_SCHEME),
) -> ValidatedSession:
    mutation = request.method.upper() not in _SAFE_METHODS
    if mutation or request.headers.get("origin") is not None:
        require_allowed_origin(request)
    validated = validate_session(
        db,
        cookie_token,
        csrf_token=csrf_token,
        require_csrf=mutation,
    )
    request.state.auth_session = validated.record
    request.state.owner = validated.owner
    return validated
