"""Auth HTTP routes: register, verify email, token (login + device attach),
refresh rotation, logout, logout-all."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ... import throttle
from ...config import CloudSettings
from ...deps import get_session, get_settings, require_access
from ...errors import CloudError
from ...features.devices import service as devices
from ...schemas import (
    LogoutRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    TokenRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from . import service as auth

router = APIRouter(prefix="/auth", tags=["auth"])


def device_challenge(public_key_b64: str) -> str:
    """Canonical, stateless possession challenge for a device public key. Signing it
    proves the client holds the matching private key; re-registration is idempotent."""
    return f"plasma-device:{public_key_b64}"


@router.post("/register", status_code=201, response_model=MessageResponse)
def register(
    body: RegisterRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: CloudSettings = Depends(get_settings),
) -> MessageResponse:
    try:
        user, token = auth.register_user(
            session, email=body.email, password=body.password, settings=settings
        )
    except auth.AuthError as error:
        raise CloudError(error.code) from error
    request.app.state.email_sender.send_verification(email=user.email, token=token)
    return MessageResponse(status="verification_sent")


@router.post("/verify-email", response_model=MessageResponse)
def verify_email(
    body: VerifyEmailRequest, session: Session = Depends(get_session)
) -> MessageResponse:
    try:
        auth.verify_email(session, raw_token=body.token)
    except auth.AuthError as error:
        raise CloudError(error.code) from error
    return MessageResponse(status="verified")


@router.post("/token", response_model=TokenResponse)
def token(
    body: TokenRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: CloudSettings = Depends(get_settings),
) -> TokenResponse:
    factory = request.app.state.session_factory
    identifier = str(body.email)
    try:
        throttle.enforce_not_locked(factory, scope="login", identifier=identifier)
    except throttle.ThrottleError as error:
        raise CloudError("throttled") from error
    try:
        user = auth.authenticate(session, email=body.email, password=body.password)
        device = devices.register_device(
            session,
            user=user,
            public_key_b64=body.device_public_key,
            challenge=device_challenge(body.device_public_key),
            signature_b64=body.device_signature,
            name=body.device_name,
        )
        issued = auth.create_session(session, user=user, device=device, settings=settings)
    except (auth.AuthError, devices.DeviceError) as error:
        # Persists despite the main transaction rolling back on this raise.
        throttle.record_failure(
            factory,
            scope="login",
            identifier=identifier,
            max_attempts=settings.max_attempts,
            lockout=settings.lockout,
        )
        raise CloudError(error.code) from error
    throttle.record_success(factory, scope="login", identifier=identifier)
    return TokenResponse(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=int(settings.access_ttl.total_seconds()),
    )


@router.post("/token/refresh", response_model=TokenResponse)
def refresh(
    body: RefreshRequest,
    session: Session = Depends(get_session),
    settings: CloudSettings = Depends(get_settings),
) -> TokenResponse:
    try:
        issued = auth.rotate_refresh(
            session, raw_refresh=body.refresh_token, settings=settings
        )
    except auth.AuthError as error:
        raise CloudError(error.code) from error
    return TokenResponse(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=int(settings.access_ttl.total_seconds()),
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    body: LogoutRequest, session: Session = Depends(get_session)
) -> MessageResponse:
    auth.revoke_session(session, raw_refresh=body.refresh_token)
    return MessageResponse(status="logged_out")


@router.post("/logout-all", response_model=MessageResponse)
def logout_all(
    claims: dict = Depends(require_access), session: Session = Depends(get_session)
) -> MessageResponse:
    auth.revoke_all_sessions(session, user_id=claims["sub"])
    return MessageResponse(status="logged_out_all")
