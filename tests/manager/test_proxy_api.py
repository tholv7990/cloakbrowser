from __future__ import annotations

from manager_backend.features.proxies.credentials import MemoryCredentialStore


def _proxy_payload(**changes):
    payload = {
        "label": "Dallas residential",
        "scheme": "socks5",
        "host": "193.169.218.22",
        "port": 50101,
        "username": "MSproxy",
        "password": "TrustProxy",
        "test_before_launch": True,
    }
    payload.update(changes)
    return payload


def _install_store(client):
    store = MemoryCredentialStore()
    client.app.state.credential_store = store
    return store


def test_create_list_and_read_proxy_never_return_credentials(client, auth_headers):
    _install_store(client)
    created = client.post("/api/v1/proxies", headers=auth_headers, json=_proxy_payload())
    assert created.status_code == 201
    body = created.json()
    assert body["username"] is None
    assert body["has_password"] is True
    assert body["masked_endpoint"] == "socks5://193.169.218.22:50101"
    assert "password" not in body

    listing = client.get("/api/v1/proxies")
    assert listing.status_code == 200
    assert listing.json() == [body]
    assert client.get(f"/api/v1/proxies/{body['id']}").json() == body


def test_patch_without_credentials_preserves_existing_secret(client, auth_headers):
    store = _install_store(client)
    created = client.post("/api/v1/proxies", headers=auth_headers, json=_proxy_payload()).json()
    updated = client.patch(
        f"/api/v1/proxies/{created['id']}",
        headers=auth_headers,
        json=_proxy_payload(label="Renamed", username=None, password=None),
    )
    assert updated.status_code == 200
    assert updated.json()["label"] == "Renamed"
    assert updated.json()["has_password"] is True
    assert len(store._values) == 1


def test_proxy_created_from_profile_flow_can_be_assigned_and_not_deleted(
    client, auth_headers
):
    _install_store(client)
    proxy = client.post("/api/v1/proxies", headers=auth_headers, json=_proxy_payload()).json()
    profile = client.post(
        "/api/v1/profiles",
        headers=auth_headers,
        json={"name": "Assigned profile", "proxy_id": proxy["id"]},
    )
    assert profile.status_code == 201
    assert profile.json()["proxy_id"] == proxy["id"]
    assert client.get("/api/v1/proxies").json()[0]["assigned_profile_count"] == 1

    rejected = client.delete(f"/api/v1/proxies/{proxy['id']}", headers=auth_headers)
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "proxy_in_use"


def test_profile_rejects_unknown_proxy_reference(client, auth_headers):
    _install_store(client)
    response = client.post(
        "/api/v1/profiles",
        headers=auth_headers,
        json={"name": "Invalid proxy", "proxy_id": "missing-proxy"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["field_errors"] == {"proxy_id": "not_found"}

    valid = client.post(
        "/api/v1/profiles", headers=auth_headers, json={"name": "Patch target"}
    ).json()
    patched = client.patch(
        f"/api/v1/profiles/{valid['id']}",
        headers=auth_headers,
        json={
            "expected_updated_at": valid["updated_at"],
            "proxy_id": "missing-proxy",
        },
    )
    assert patched.status_code == 422
    assert patched.json()["error"]["field_errors"] == {"proxy_id": "not_found"}


def test_parse_route_returns_editable_fields_but_not_password(client, auth_headers):
    _install_store(client)
    response = client.post(
        "/api/v1/proxies/parse",
        headers=auth_headers,
        json={"raw": "socks5://MSproxy:TrustProxy@193.169.218.22:50101"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "scheme": "socks5",
        "host": "193.169.218.22",
        "port": 50101,
        "username": "MSproxy",
        "has_password": True,
    }


def test_duplicate_proxy_label_is_case_insensitive(client, auth_headers):
    store = _install_store(client)
    assert client.post("/api/v1/proxies", headers=auth_headers, json=_proxy_payload()).status_code == 201
    duplicate = client.post(
        "/api/v1/proxies",
        headers=auth_headers,
        json=_proxy_payload(label="  DALLAS RESIDENTIAL  "),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "proxy_label_conflict"
    assert len(store._values) == 1


def test_direct_proxy_requires_no_endpoint_or_credentials(client, auth_headers):
    _install_store(client)
    response = client.post(
        "/api/v1/proxies",
        headers=auth_headers,
        json=_proxy_payload(
            label="Direct", scheme="direct", host="", port=None, username=None, password=None
        ),
    )
    assert response.status_code == 201
    assert response.json()["masked_endpoint"] == "direct"
    assert response.json()["has_password"] is False
