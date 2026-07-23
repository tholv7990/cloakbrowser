"""Token primitives.

- **Refresh tokens** are opaque high-entropy strings; only their SHA-256 is stored
  (``sessions.refresh_token_hash``), so a DB leak can't replay them.
- **Access tokens** are short EdDSA JWS (reusing the entitlement signer), carrying
  ``typ=access`` so an entitlement can never be presented as an access token.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .entitlements import EntitlementError, sign_entitlement, verify_entitlement


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """SHA-256 hex of a token — the only representation stored/looked up."""
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def mint_access_token(
    *,
    user_id: str,
    session_id: str,
    device_id: str,
    private_key: Ed25519PrivateKey,
    now: datetime,
    ttl: timedelta,
) -> str:
    claims = {
        "typ": "access",
        "sub": user_id,
        "sid": session_id,
        "device_id": device_id,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return sign_entitlement(claims, private_key)


def verify_access_token(token: str, public_key: Ed25519PublicKey) -> dict:
    """Verify signature + that this is an access token. Callers still check exp."""
    claims = verify_entitlement(token, public_key)
    if claims.get("typ") != "access":
        raise EntitlementError("not_an_access_token")
    return claims
