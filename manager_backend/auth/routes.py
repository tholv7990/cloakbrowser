from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..dependencies import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    get_session,
    require_allowed_origin,
    require_authenticated_session,
)
from ..errors import ManagerError
from ..models import Owner, utc_now
from .passwords import hash_password, password_needs_rehash, verify_password
from .schemas import (
    AuthStatus,
    ChangePasswordRequest,
    LoginRequest,
    OwnerSessionRead,
    OwnerSetupRequest,
)
from .sessions import (
    IssuedSession,
    ValidatedSession,
    issue_session,
    revoke_all_sessions,
    revoke_session,
)


router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

# Remember-me: keep the owner signed in across app restarts. Without a Max-Age the
# session/CSRF cookies are session cookies that die when the webview closes, forcing
# a re-login on every launch. The server-side session itself never expires until an
# explicit logout/lock (see sessions.py), so this window just bounds how long the
# browser will replay the cookie. 30 days matches the usual "remember me" horizon.
_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


def _cookie_policy(allowed_origin: str) -> tuple[str, bool]:
    """(SameSite, Secure) for the session/CSRF cookies, keyed off the UI origin.

    The packaged desktop serves the UI from http://tauri.localhost while the API
    binds http://127.0.0.1 — a *different site*. A SameSite=Strict cookie is never
    sent on the webview's cross-site API calls, so login works but every later call
    401s. Cross-site requires SameSite=None, which requires Secure; Chromium treats
    127.0.0.1 as a secure context, so Secure rides plain-http loopback. The browser
    dev flow is same-origin (Vite proxy) and keeps the stricter Strict."""
    host = (urlparse(allowed_origin).hostname or "").lower()
    if host in ("127.0.0.1", "localhost"):  # same-origin dev flow
        return "strict", allowed_origin.startswith("https://")
    return "none", True  # cross-site desktop webview


def _set_session_cookie(request: Request, response: Response, issued: IssuedSession) -> None:
    samesite, secure = _cookie_policy(request.app.state.settings.allowed_origin)
    response.set_cookie(
        SESSION_COOKIE,
        issued.token,
        max_age=_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        issued.csrf_token,
        max_age=_COOKIE_MAX_AGE_SECONDS,
        httponly=False,
        secure=secure,
        samesite=samesite,
        path="/",
    )


def _clear_session_cookies(request: Request, response: Response) -> None:
    """Delete the session/CSRF cookies with the same SameSite/Secure policy they
    were set with, so set and clear stay consistent (desktop = None/Secure)."""
    samesite, secure = _cookie_policy(request.app.state.settings.allowed_origin)
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", samesite=samesite, secure=secure)


def _session_read(owner: Owner, issued: IssuedSession) -> OwnerSessionRead:
    return OwnerSessionRead(
        email=owner.email,
        csrf_token=issued.csrf_token,
    )


@router.get("/status", response_model=AuthStatus)
def auth_status(db: Session = Depends(get_session)) -> AuthStatus:
    return AuthStatus(setup_required=(db.scalar(select(func.count(Owner.id))) == 0))


@router.post("/setup", response_model=OwnerSessionRead, status_code=status.HTTP_201_CREATED)
def setup_owner(
    payload: OwnerSetupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> OwnerSessionRead:
    require_allowed_origin(request)
    if db.scalar(select(func.count(Owner.id))):
        raise ManagerError("owner_already_configured", "The local owner is already configured.", 409)
    owner = Owner(email=str(payload.email), password_hash=hash_password(payload.password))
    db.add(owner)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ManagerError("owner_already_configured", "The local owner is already configured.", 409)
    db.refresh(owner)
    issued = issue_session(db, owner)
    _set_session_cookie(request, response, issued)
    return _session_read(owner, issued)


@router.post("/login", response_model=OwnerSessionRead)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> OwnerSessionRead:
    require_allowed_origin(request)
    failures = request.app.state.login_failures
    owner = db.scalar(select(Owner).where(Owner.email == str(payload.email)))
    if owner is None or not verify_password(owner.password_hash, payload.password):
        failures["count"] = failures.get("count", 0) + 1
        if failures["count"] > 5:
            await asyncio.sleep(min(1.0, 0.1 * (failures["count"] - 5)))
        raise ManagerError("invalid_credentials", "The email or password is incorrect.", 401)
    failures["count"] = 0
    if password_needs_rehash(owner.password_hash):
        owner.password_hash = hash_password(payload.password)
        db.commit()
    issued = issue_session(db, owner)
    _set_session_cookie(request, response, issued)
    return _session_read(owner, issued)


@router.get("/session", response_model=OwnerSessionRead)
def current_session(
    request: Request,
    validated: ValidatedSession = Depends(require_authenticated_session),
) -> OwnerSessionRead:
    return OwnerSessionRead(
        email=validated.owner.email,
        csrf_token=request.cookies.get(CSRF_COOKIE, ""),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
    validated: ValidatedSession = Depends(require_authenticated_session),
) -> None:
    revoke_session(db, validated.record)
    _clear_session_cookies(request, response)


@router.post("/lock", status_code=status.HTTP_204_NO_CONTENT)
def lock(
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
    validated: ValidatedSession = Depends(require_authenticated_session),
) -> None:
    revoke_all_sessions(db, validated.owner.id)
    _clear_session_cookies(request, response)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
    validated: ValidatedSession = Depends(require_authenticated_session),
) -> None:
    owner = validated.owner
    if not verify_password(owner.password_hash, payload.current_password):
        raise ManagerError("invalid_credentials", "The current password is incorrect.", 401)
    owner.password_hash = hash_password(payload.new_password)
    owner.password_changed_at = utc_now()
    db.commit()
    revoke_all_sessions(db, owner.id)
    _clear_session_cookies(request, response)
