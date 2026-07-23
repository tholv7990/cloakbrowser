"""Entitlement signing (EdDSA) — the signed document the desktop trusts.

A compact JWS (``header.payload.signature``, base64url) signed with the cloud's
Ed25519 private key. We use ``cryptography`` directly (the same library the desktop
already uses to verify the browser binary, cloakbrowser/download.py:663) rather than
add a PyJWT dependency. The desktop validates the token with the cloud **public**
key pinned in the app — a public key is not a secret, so nothing secret is embedded.

Only Ed25519 verification is ever performed, so there is no algorithm-confusion
surface (we never dispatch on the token's ``alg`` header).
"""

from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class EntitlementError(Exception):
    """Raised for a malformed token or a signature that does not verify."""


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


_HEADER = _b64u(
    json.dumps({"alg": "EdDSA", "typ": "PLASMA-ENT"}, separators=(",", ":")).encode()
)


def sign_entitlement(claims: dict, private_key: Ed25519PrivateKey) -> str:
    """Return a compact EdDSA token over ``claims`` (non-secret claims only)."""
    payload = _b64u(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{_HEADER}.{payload}".encode("ascii")
    signature = private_key.sign(signing_input)
    return f"{_HEADER}.{payload}.{_b64u(signature)}"


def verify_entitlement(token: str, public_key: Ed25519PublicKey) -> dict:
    """Verify the signature and return the claims, or raise EntitlementError.

    This mirrors what the desktop does with the pinned public key; validity is the
    signature — callers still must check exp / device_id / version on the claims.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise EntitlementError("malformed_token")
    header_b64, payload_b64, signature_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    try:
        public_key.verify(_b64u_decode(signature_b64), signing_input)
    except Exception as error:  # InvalidSignature or malformed base64
        raise EntitlementError("bad_signature") from error
    try:
        return json.loads(_b64u_decode(payload_b64))
    except (ValueError, json.JSONDecodeError) as error:
        raise EntitlementError("malformed_payload") from error


# --- key helpers (the pinned public key ships in the desktop app) --------------


def generate_signing_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def public_key_to_b64(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode("ascii")


def public_key_from_b64(value: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(value))


def private_key_from_pem(pem: bytes, password: bytes | None = None) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(pem, password=password)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("not an Ed25519 private key")
    return key
