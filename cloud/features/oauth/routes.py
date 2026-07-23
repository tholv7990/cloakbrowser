"""OAuth PKCE routes.

/oauth/authorize — the hosted login page authenticates the user and gets an
authorization code (in a full browser flow it 302s to redirect_uri?code=…&state=…;
here it returns the code as JSON for the page to redirect with).
/oauth/token — the desktop exchanges the code + PKCE verifier + device for tokens.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ... import throttle
from ...config import CloudSettings
from ...deps import get_session, get_settings
from ...errors import CloudError
from ...features.auth import service as auth
from ...features.devices import service as devices
from ...schemas import (
    AuthorizeRequest,
    AuthorizeResponse,
    OAuthTokenRequest,
    TokenResponse,
)
from . import service as oauth
from .login_page import LOGIN_CSP, LOGIN_HTML

router = APIRouter(prefix="/oauth", tags=["oauth"])


def _device_challenge(public_key_b64: str) -> str:
    return f"plasma-device:{public_key_b64}"


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page() -> HTMLResponse:
    # Static page; it reads redirect_uri/code_challenge/state from the URL client-side.
    return HTMLResponse(content=LOGIN_HTML, headers={"Content-Security-Policy": LOGIN_CSP})


@router.post("/authorize", response_model=AuthorizeResponse)
def authorize(
    body: AuthorizeRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: CloudSettings = Depends(get_settings),
) -> AuthorizeResponse:
    factory = request.app.state.session_factory
    if not oauth.is_loopback_redirect_uri(body.redirect_uri):
        raise CloudError("invalid_request")
    identifier = str(body.email)
    try:
        throttle.enforce_on(session, scope="login", identifier=identifier)
    except throttle.ThrottleError as error:
        raise CloudError("throttled") from error
    try:
        user = auth.authenticate(session, email=body.email, password=body.password)
    except auth.AuthError as error:
        throttle.record_failure(
            factory,
            scope="login",
            identifier=identifier,
            max_attempts=settings.max_attempts,
            lockout=settings.lockout,
        )
        raise CloudError(error.code) from error
    throttle.record_success_on(session, scope="login", identifier=identifier)
    code = oauth.create_authorization_code(
        session,
        user=user,
        code_challenge=body.code_challenge,
        redirect_uri=body.redirect_uri,
        settings=settings,
    )
    return AuthorizeResponse(code=code, redirect_uri=body.redirect_uri)


@router.post("/token", response_model=TokenResponse)
def oauth_token(
    body: OAuthTokenRequest,
    session: Session = Depends(get_session),
    settings: CloudSettings = Depends(get_settings),
) -> TokenResponse:
    try:
        user = oauth.exchange_code(
            session,
            code=body.code,
            code_verifier=body.code_verifier,
            redirect_uri=body.redirect_uri,
        )
        device = devices.register_device(
            session,
            user=user,
            public_key_b64=body.device_public_key,
            challenge=_device_challenge(body.device_public_key),
            signature_b64=body.device_signature,
            name=body.device_name,
        )
        issued = auth.create_session(session, user=user, device=device, settings=settings)
    except (auth.AuthError, devices.DeviceError) as error:
        raise CloudError(error.code) from error
    return TokenResponse(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=int(settings.access_ttl.total_seconds()),
    )
