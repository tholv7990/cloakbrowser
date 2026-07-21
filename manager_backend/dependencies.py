from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .auth.sessions import ValidatedSession, validate_session
from .errors import ManagerError


SESSION_COOKIE = "cloak_session"
CSRF_HEADER = "x-csrf-token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


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
    request: Request, db: Session = Depends(get_session)
) -> ValidatedSession:
    mutation = request.method.upper() not in _SAFE_METHODS
    if mutation:
        require_allowed_origin(request)
    validated = validate_session(
        db,
        request.cookies.get(SESSION_COOKIE),
        csrf_token=request.headers.get(CSRF_HEADER),
        require_csrf=mutation,
    )
    request.state.auth_session = validated.record
    request.state.owner = validated.owner
    return validated
