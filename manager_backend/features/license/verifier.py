"""Offline verification of the cloud's signed entitlement.

The desktop is a *client* of the cloud, so it never signs — it only verifies the
compact EdDSA JWS the cloud issued, using the cloud's Ed25519 **public** key pinned
in the build (a public key is not a secret). The wire format here MUST match
``cloud/entitlements.py`` byte-for-byte (same header, same ``sort_keys`` payload) or
verification fails; the license tests sign with the cloud helper and verify here,
which cross-checks that the two stay in lock-step.

Only Ed25519 verification is ever performed, so there is no algorithm-confusion
surface (we never dispatch on the token's ``alg`` header).
"""

from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class EntitlementError(Exception):
    """Malformed token or a signature that does not verify."""


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def public_key_from_b64(value: str) -> Ed25519PublicKey:
    """Load the pinned public key (base64 of the 32 raw Ed25519 bytes)."""
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(value))


def verify_entitlement(token: str, public_key: Ed25519PublicKey) -> dict:
    """Return the claims iff the signature verifies, else raise EntitlementError.

    The signature is the only thing proven here — callers still check exp /
    offline_grace_deadline / device_id on the returned claims.
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
