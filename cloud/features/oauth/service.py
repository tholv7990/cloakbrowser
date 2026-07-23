"""OAuth 2.1 Authorization Code + PKCE (S256).

The hosted login page authenticates the user and calls create_authorization_code;
the desktop then exchanges the code + its PKCE code_verifier at /oauth/token. Only
the SHA-256 of the code and the code_challenge are stored — never the verifier.
Codes are single-use and short-lived.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime

from sqlalchemy import select

from ... import models
from ...config import CloudSettings
from ...db import ensure_aware_utc, utc_now
from ...tokens import hash_token
from ..auth.service import AuthError


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def create_authorization_code(
    session,
    *,
    user: models.User,
    code_challenge: str,
    redirect_uri: str,
    settings: CloudSettings,
    now: datetime | None = None,
) -> str:
    now = now or utc_now()
    raw_code = secrets.token_urlsafe(32)
    session.add(
        models.OAuthAuthorizationCode(
            code_hash=hash_token(raw_code),
            user_id=user.id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method="S256",
            expires_at=now + settings.oauth_code_ttl,
        )
    )
    session.flush()
    return raw_code


def exchange_code(
    session,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    now: datetime | None = None,
) -> models.User:
    now = now or utc_now()
    row = session.execute(
        select(models.OAuthAuthorizationCode).where(
            models.OAuthAuthorizationCode.code_hash == hash_token(code)
        )
    ).scalar_one_or_none()
    if (
        row is None
        or row.consumed_at is not None
        or ensure_aware_utc(row.expires_at) <= now
        or row.redirect_uri != redirect_uri
        or _s256(code_verifier) != row.code_challenge
    ):
        raise AuthError("invalid_grant")
    row.consumed_at = now  # single-use
    return session.get(models.User, row.user_id)
