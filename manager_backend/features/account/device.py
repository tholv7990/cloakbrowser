"""Per-install device identity: an Ed25519 keypair the desktop uses to prove
possession to the cloud. The private key is generated once and kept in the OS
credential store; the cloud pins the public key to the account (device-bound
sessions + entitlements). Matches the cloud's device challenge exactly:
``plasma-device:{public_key_b64}`` signed with the private key (base64, raw bytes).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .secrets import SecretStore

DEVICE_KEY_REF = "device-private-key"  # PEM, in the secret store


@dataclass
class DeviceIdentity:
    public_key_b64: str
    _private: Ed25519PrivateKey

    def signature_b64(self) -> str:
        """Base64 signature over the canonical device challenge."""
        challenge = f"plasma-device:{self.public_key_b64}".encode("ascii")
        return base64.b64encode(self._private.sign(challenge)).decode("ascii")


def _public_b64(private: Ed25519PrivateKey) -> str:
    raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode("ascii")


def get_or_create_device(store: SecretStore) -> DeviceIdentity:
    pem = store.get(DEVICE_KEY_REF)
    if pem:
        private = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
        if not isinstance(private, Ed25519PrivateKey):
            raise ValueError("stored device key is not Ed25519")
    else:
        private = Ed25519PrivateKey.generate()
        pem_bytes = private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        store.put(DEVICE_KEY_REF, pem_bytes.decode("ascii"))
    return DeviceIdentity(public_key_b64=_public_b64(private), _private=private)
