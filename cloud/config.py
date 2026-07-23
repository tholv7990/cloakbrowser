"""Cloud runtime settings.

Secrets come from the environment in production (never committed); tests build a
``CloudSettings`` directly with a generated keypair + throwaway pepper. One
Ed25519 key signs both entitlements and access tokens; its public half is the key
pinned in the desktop app.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from datetime import timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .entitlements import generate_signing_keypair, private_key_from_pem


@dataclass
class CloudSettings:
    activation_pepper: bytes
    signing_private_key: Ed25519PrivateKey
    access_ttl: timedelta = timedelta(minutes=10)
    refresh_ttl: timedelta = timedelta(days=30)
    entitlement_ttl: timedelta = timedelta(hours=24)
    offline_grace: timedelta = timedelta(days=7)
    email_verification_ttl: timedelta = timedelta(hours=24)
    password_reset_ttl: timedelta = timedelta(hours=1)
    # Abuse controls (auth_throttle): attempts allowed before lockout, and how long.
    max_attempts: int = 8
    lockout: timedelta = timedelta(minutes=15)

    @property
    def signing_public_key(self) -> Ed25519PublicKey:
        return self.signing_private_key.public_key()


def load_settings() -> CloudSettings:
    pepper_b64 = os.environ.get("PLASMA_ACTIVATION_PEPPER")
    key_pem = os.environ.get("PLASMA_SIGNING_PRIVATE_KEY_PEM")
    if not pepper_b64 or not key_pem:
        raise RuntimeError(
            "PLASMA_ACTIVATION_PEPPER (base64) and PLASMA_SIGNING_PRIVATE_KEY_PEM "
            "must be set"
        )
    return CloudSettings(
        activation_pepper=base64.b64decode(pepper_b64),
        signing_private_key=private_key_from_pem(key_pem.encode("ascii")),
    )


def generate_test_settings() -> CloudSettings:
    """A self-contained settings object for tests (fresh key + throwaway pepper)."""
    private_key, _public = generate_signing_keypair()
    return CloudSettings(
        activation_pepper=b"test-pepper-0123456789abcdef",
        signing_private_key=private_key,
    )
