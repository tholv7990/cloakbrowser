from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from ...errors import ManagerError


SERVICE_NAME = "cloakbrowser-manager-proxy"


@dataclass(frozen=True, slots=True)
class ProxyCredential:
    username: str
    password: str


class CredentialStore(Protocol):
    def put(self, reference: str, credential: ProxyCredential) -> None: ...

    def get(self, reference: str) -> ProxyCredential | None: ...

    def delete(self, reference: str) -> None: ...


def _unavailable() -> ManagerError:
    return ManagerError(
        "credential_store_unavailable",
        "The secure credential store is unavailable.",
        503,
    )


class MemoryCredentialStore:
    def __init__(self):
        self._values: dict[str, ProxyCredential] = {}

    def put(self, reference: str, credential: ProxyCredential) -> None:
        self._values[reference] = credential

    def get(self, reference: str) -> ProxyCredential | None:
        return self._values.get(reference)

    def delete(self, reference: str) -> None:
        self._values.pop(reference, None)


class KeyringCredentialStore:
    def __init__(self, *, keyring_backend=None):
        if keyring_backend is None:
            import keyring

            keyring_backend = keyring
        self._keyring = keyring_backend

    def put(self, reference: str, credential: ProxyCredential) -> None:
        payload = json.dumps(
            {"username": credential.username, "password": credential.password},
            separators=(",", ":"),
        )
        try:
            self._keyring.set_password(SERVICE_NAME, reference, payload)
        except Exception:
            raise _unavailable() from None

    def get(self, reference: str) -> ProxyCredential | None:
        try:
            payload = self._keyring.get_password(SERVICE_NAME, reference)
            if payload is None:
                return None
            value = json.loads(payload)
            if (
                not isinstance(value, dict)
                or not isinstance(value.get("username"), str)
                or not isinstance(value.get("password"), str)
            ):
                raise ValueError
            return ProxyCredential(value["username"], value["password"])
        except Exception:
            raise _unavailable() from None

    def delete(self, reference: str) -> None:
        # Idempotent: deleting a credential that does not exist is success. The
        # real keyring raises PasswordDeleteError for a missing entry — treat only
        # that as "already absent". Any other failure (backend unavailable,
        # permission, corruption) is a genuine error and must surface, so startup
        # reconciliation keeps the journal row and retries rather than dropping it.
        try:
            from keyring.errors import PasswordDeleteError
        except Exception:  # keyring not importable in this environment
            PasswordDeleteError = ()  # type: ignore[assignment]
        try:
            self._keyring.delete_password(SERVICE_NAME, reference)
        except PasswordDeleteError:
            return
        except Exception:
            raise _unavailable() from None
