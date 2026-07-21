from __future__ import annotations

import pytest

from manager_backend.errors import ManagerError
from manager_backend.features.proxies.credentials import (
    KeyringCredentialStore,
    MemoryCredentialStore,
    ProxyCredential,
)


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
