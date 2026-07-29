from __future__ import annotations

import pytest
from keyring.errors import KeyringError, PasswordDeleteError

from manager_backend.errors import ManagerError
from manager_backend.features.proxies.credentials import (
    KeyringCredentialStore,
    MemoryCredentialStore,
    ProxyCredential,
)


class FakeWindowsKeyring:
    """Mimics the real Windows keyring: delete_password raises PasswordDeleteError
    when the credential does not exist (this is what breaks a naive delete)."""

    def __init__(self):
        self._data: dict[tuple[str, str], str] = {}

    def set_password(self, service, ref, payload):
        self._data[(service, ref)] = payload

    def get_password(self, service, ref):
        return self._data.get((service, ref))

    def delete_password(self, service, ref):
        if (service, ref) not in self._data:
            raise PasswordDeleteError("no such password")
        del self._data[(service, ref)]


def test_memory_store_round_trips_and_deletes_credentials():
    store = MemoryCredentialStore()
    credential = ProxyCredential("alice", "secret")
    store.put("ref-one", credential)
    assert store.get("ref-one") == credential
    store.delete("ref-one")
    assert store.get("ref-one") is None


def test_keyring_store_maps_provider_errors_without_leaking_details():
    class BrokenKeyring:
        def set_password(self, *_args):
            raise RuntimeError("provider path and secret")

    store = KeyringCredentialStore(keyring_backend=BrokenKeyring())
    with pytest.raises(ManagerError) as error:
        store.put("opaque-ref", ProxyCredential("alice", "secret"))
    assert error.value.code == "credential_store_unavailable"
    assert "secret" not in error.value.message


def test_keyring_store_rejects_malformed_stored_json():
    class MalformedKeyring:
        def get_password(self, *_args):
            return "not-json"

    store = KeyringCredentialStore(keyring_backend=MalformedKeyring())
    with pytest.raises(ManagerError) as error:
        store.get("opaque-ref")
    assert error.value.code == "credential_store_unavailable"


def test_keyring_delete_of_existing_credential_removes_it():
    backend = FakeWindowsKeyring()
    store = KeyringCredentialStore(keyring_backend=backend)
    store.put("ref-1", ProxyCredential("alice", "secret"))
    store.delete("ref-1")
    assert store.get("ref-1") is None


def test_keyring_delete_of_missing_credential_is_idempotent_success():
    # The real Windows keyring raises PasswordDeleteError here; that must be
    # treated as success, not credential_store_unavailable — otherwise startup
    # reconciliation of a never-written ref fails forever.
    backend = FakeWindowsKeyring()
    store = KeyringCredentialStore(keyring_backend=backend)
    store.delete("never-written")  # must not raise


def test_keyring_delete_reraises_genuine_backend_failure():
    class BrokenKeyring:
        def delete_password(self, *_args):
            raise KeyringError("backend unavailable")

    store = KeyringCredentialStore(keyring_backend=BrokenKeyring())
    with pytest.raises(ManagerError) as error:
        store.delete("ref-1")
    assert error.value.code == "credential_store_unavailable"
