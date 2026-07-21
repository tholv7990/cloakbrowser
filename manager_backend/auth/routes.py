from __future__ import annotations

import asyncio
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
def _set_session_cookie(request: Request, response: Response, issued: IssuedSession) -> None:
    secure = request.app.state.settings.allowed_origin.startswith("https://")
    response.set_cookie(
        SESSION_COOKIE,
        issued.token,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        issued.csrf_token,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )


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
    response: Response,
    db: Session = Depends(get_session),
    validated: ValidatedSession = Depends(require_authenticated_session),
) -> None:
    revoke_session(db, validated.record)
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", samesite="strict")


@router.post("/lock", status_code=status.HTTP_204_NO_CONTENT)
def lock(
    response: Response,
    db: Session = Depends(get_session),
    validated: ValidatedSession = Depends(require_authenticated_session),
) -> None:
    revoke_all_sessions(db, validated.owner.id)
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", samesite="strict")


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
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
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", samesite="strict")
