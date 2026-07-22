from __future__ import annotations

from manager_backend.features.proxies.credentials import MemoryCredentialStore, ProxyCredential
from manager_backend.features.proxies.providers import (
    GeneratedProxy,
    IPRoyalApi,
    _store_ref,
    build_seveneleven_routes,
)


def test_seveneleven_routes_encode_region_and_unique_sessions():
    credential = ProxyCredential("quantumsub", "Secret123")
    routes = build_seveneleven_routes(credential, 3, "us", "sticky")
    assert len(routes) == 3
    assert {route.username for route in routes} == {r.username for r in routes}  # sanity
    assert len({route.username for route in routes}) == 3  # unique sessions
    for route in routes:
        assert route.host == "global.711proxy.com" and route.port == 20000
        assert route.password == "Secret123"
        assert route.username.startswith("quantumsub-region-US-session-")
        assert route.username.endswith("-sessTime-30")  # sticky window
    # rotating uses the short window
    rotating = build_seveneleven_routes(credential, 1, "US", "rotating")
    assert rotating[0].username.endswith("-sessTime-5")


def test_iproyal_to_proxy_rewrites_the_sticky_session():
    first = IPRoyalApi._to_proxy("geo.iproyal.com:12321:user:base_session-OLD1_lifetime-1h", "sticky")
    assert first.host == "geo.iproyal.com" and first.port == 12321 and first.username == "user"
    assert "_session-OLD1" not in first.password
    assert "_lifetime-24h" in first.password
    # random rotation keeps the returned password untouched
    random = IPRoyalApi._to_proxy("geo.iproyal.com:12321:user:plainpass", "random")
    assert random.password == "plainpass"


def _install_store(client):
    store = MemoryCredentialStore()
    client.app.state.credential_store = store
    return store


class _FakeProviderClient:
    def __init__(self, proxies):
        self._proxies = proxies
        self.calls = []

    def generate(self, provider, credential, count, country, session_type):
        self.calls.append((provider, credential, count, country, session_type))
        return self._proxies


def test_list_providers_never_leaks_secrets(client, auth_headers):
    _install_store(client)
    listing = client.get("/api/v1/proxies/providers").json()
    assert listing == [
        {"id": "iproyal", "name": "IPRoyal", "configured": False},
        {"id": "seveneleven", "name": "711Proxy", "configured": False},
    ]

    saved = client.put(
        "/api/v1/proxies/providers/iproyal",
        headers=auth_headers,
        json={"provider": "iproyal", "api_token": "sekret-token"},
    )
    assert saved.status_code == 200
    assert saved.json() == {"id": "iproyal", "name": "IPRoyal", "configured": True}

    after = client.get("/api/v1/proxies/providers").json()
    assert after[0]["configured"] is True
    assert "sekret-token" not in str(after)


def test_put_stores_secret_in_credential_store_not_a_response(client, auth_headers):
    store = _install_store(client)
    saved = client.put(
        "/api/v1/proxies/providers/seveneleven",
        headers=auth_headers,
        json={"provider": "seveneleven", "username": "quantumsub", "password": "Secret123"},
    )
    assert saved.status_code == 200
    assert "Secret123" not in saved.text
    credential = store.get(_store_ref("seveneleven"))
    assert credential is not None
    assert credential.username == "quantumsub"
    assert credential.password == "Secret123"


def test_put_rejects_path_body_mismatch(client, auth_headers):
    _install_store(client)
    response = client.put(
        "/api/v1/proxies/providers/iproyal",
        headers=auth_headers,
        json={"provider": "seveneleven", "username": "u", "password": "p"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "proxy_provider_mismatch"


def test_put_iproyal_requires_token(client, auth_headers):
    _install_store(client)
    response = client.put(
        "/api/v1/proxies/providers/iproyal",
        headers=auth_headers,
        json={"provider": "iproyal"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "proxy_provider_invalid"


def test_generate_requires_a_configured_provider(client, auth_headers):
    _install_store(client)
    response = client.post(
        "/api/v1/proxies/providers/generate",
        headers=auth_headers,
        json={"provider": "iproyal", "count": 2, "country": "US", "session_type": "rotating"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "proxy_provider_not_configured"


def test_generate_seveneleven_builds_unique_local_routes_into_the_pool(client, auth_headers):
    _install_store(client)
    client.put(
        "/api/v1/proxies/providers/seveneleven",
        headers=auth_headers,
        json={"provider": "seveneleven", "username": "quantumsub", "password": "Secret123"},
    )
    result = client.post(
        "/api/v1/proxies/providers/generate",
        headers=auth_headers,
        json={"provider": "seveneleven", "count": 3, "country": "US", "session_type": "sticky"},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["created"] == 3
    assert len(body["proxy_ids"]) == 3
    assert "Secret123" not in result.text

    listing = client.get("/api/v1/proxies").json()
    assert len(listing) == 3
    assert len({row["label"] for row in listing}) == 3  # unique labels
    for row in listing:
        assert row["organization"] == "711Proxy"
        assert row["scheme"] == "socks5h"
        assert row["host"] == "global.711proxy.com"
        assert row["port"] == 20000
        assert row["proxy_type"] == "residential"
        assert row["country"] == "US"
        assert row["has_password"] is True
        assert row["username"] is None


def test_generate_iproyal_uses_injected_client_and_inserts_rows(client, auth_headers):
    _install_store(client)
    fake = _FakeProviderClient([
        GeneratedProxy("geo.iproyal.com", 12321, "user-a", "pass-a"),
        GeneratedProxy("geo.iproyal.com", 12321, "user-b", "pass-b"),
    ])
    client.app.state.proxy_provider_client = fake
    client.put(
        "/api/v1/proxies/providers/iproyal",
        headers=auth_headers,
        json={"provider": "iproyal", "api_token": "tok-123"},
    )
    result = client.post(
        "/api/v1/proxies/providers/generate",
        headers=auth_headers,
        json={"provider": "iproyal", "count": 2, "country": "GB", "session_type": "sticky"},
    )
    assert result.status_code == 200, result.text
    assert result.json()["created"] == 2
    assert "pass-a" not in result.text

    # Client received the stored token in the credential's password slot.
    provider, credential, count, country, session_type = fake.calls[0]
    assert provider == "iproyal"
    assert credential.password == "tok-123"
    assert (count, country, session_type) == (2, "GB", "sticky")

    listing = client.get("/api/v1/proxies").json()
    assert {row["organization"] for row in listing} == {"IPRoyal"}
    assert all(row["proxy_type"] == "residential" for row in listing)
    assert all(row["country"] == "GB" for row in listing)


def test_generate_count_is_clamped_by_validation(client, auth_headers):
    _install_store(client)
    client.put(
        "/api/v1/proxies/providers/seveneleven",
        headers=auth_headers,
        json={"provider": "seveneleven", "username": "quantumsub", "password": "Secret123"},
    )
    too_many = client.post(
        "/api/v1/proxies/providers/generate",
        headers=auth_headers,
        json={"provider": "seveneleven", "count": 51, "country": "US", "session_type": "sticky"},
    )
    assert too_many.status_code == 422
