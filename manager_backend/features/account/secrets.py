"""A tiny string secret store for account credentials (device private key, cloud
refresh token). The proxy CredentialStore is typed for username/password pairs, so
this is a separate generic key->string store backed by the OS credential manager
(DPAPI on Windows via keyring). Secrets here are NEVER logged or returned by the API.
"""

from __future__ import annotations

from typing import Protocol

SERVICE_NAME = "cloakbrowser-manager-account"


class SecretStore(Protocol):
    def put(self, key: str, value: str) -> None: ...

    def get(self, key: str) -> str | None: ...

    def delete(self, key: str) -> None: ...


class MemorySecretStore:
    """In-process store for tests (no OS keyring)."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def put(self, key: str, value: str) -> None:
        self._values[key] = value

    def get(self, key: str) -> str | None:
        return self._values.get(key)

    def delete(self, key: str) -> None:
        self._values.pop(key, None)


class KeyringSecretStore:
    def __init__(self, *, keyring_backend=None) -> None:
        if keyring_backend is None:
            import keyring

            keyring_backend = keyring
        self._keyring = keyring_backend

    def put(self, key: str, value: str) -> None:
        self._keyring.set_password(SERVICE_NAME, key, value)

    def get(self, key: str) -> str | None:
        return self._keyring.get_password(SERVICE_NAME, key)

    def delete(self, key: str) -> None:
        try:
            self._keyring.delete_password(SERVICE_NAME, key)
        except Exception:
            pass  # already absent -> deletion is idempotent
