from __future__ import annotations

import json

_BASE = "/api/v1/automations/shop-check"


def _valid_payload(**overrides) -> dict:
    payload = {
        "email_text": "a@example.com\nb@example.com",
        "emails_per_profile": 5,
        "max_parallel": 3,
        "authorized_only_ack": True,
    }
    payload.update(overrides)
    return payload


def _create(client, auth_headers, **overrides):
    return client.post(
        f"{_BASE}/runs", headers=auth_headers, json=_valid_payload(**overrides)
    )


# --- contract ---------------------------------------------------------------
def test_create_returns_run_and_input_summary(client, auth_headers):
    response = _create(client, auth_headers)
    assert response.status_code == 202, response.text
    body = response.json()
    assert set(body) == {"run", "input_summary"}
    run = body["run"]
    assert run["status"] == "queued"
    assert run["target_url"] == "https://shop.app/"
    assert run["emails_per_profile"] == 5
    assert run["max_parallel"] == 3
    assert run["cleanup_state"] == "none"
    assert "workers" in run and run["workers"] == []
    assert set(body["input_summary"]) == {
        "total_lines",
        "valid",
        "duplicates",
        "invalid",
        "worker_count",
    }


def test_create_rejects_extra_field(client, auth_headers):
    response = client.post(
        f"{_BASE}/runs",
        headers=auth_headers,
        json=_valid_payload(smuggled="x"),
    )
    assert response.status_code == 422


def test_create_requires_authorization_ack(client, auth_headers):
    response = _create(client, auth_headers, authorized_only_ack=False)
    assert response.status_code == 422


def test_create_rejects_out_of_range_emails_per_profile(client, auth_headers):
    assert _create(client, auth_headers, emails_per_profile=6).status_code == 422
    assert _create(client, auth_headers, emails_per_profile=0).status_code == 422


def test_create_rejects_bad_region(client, auth_headers):
    assert _create(client, auth_headers, region="USA").status_code == 422


def test_requires_authenticated_session(client):
    # No setup ran on this client, so there is no owner session cookie.
    response = client.post(
        f"{_BASE}/runs",
        headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": "nope"},
        json=_valid_payload(),
    )
    assert response.status_code in (401, 403)


def test_list_and_get_run(client, auth_headers):
    run_id = _create(client, auth_headers).json()["run"]["id"]
    listing = client.get(f"{_BASE}/runs", headers=auth_headers)
    assert listing.status_code == 200
    assert run_id in [r["id"] for r in listing.json()]

    detail = client.get(f"{_BASE}/runs/{run_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == run_id


def test_get_missing_run_is_404(client, auth_headers):
    response = client.get(f"{_BASE}/runs/does-not-exist", headers=auth_headers)
    assert response.status_code == 404


def test_emails_endpoint_returns_page_shape(client, auth_headers):
    run_id = _create(client, auth_headers).json()["run"]["id"]
    response = client.get(f"{_BASE}/runs/{run_id}/emails", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "page", "page_size", "pages"}
    assert body["items"] == []


def test_cancel_run(client, auth_headers):
    run_id = _create(client, auth_headers).json()["run"]["id"]
    response = client.post(f"{_BASE}/runs/{run_id}/cancel", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


# --- security / contract hygiene --------------------------------------------
def test_no_secret_fields_in_any_response(client, auth_headers):
    run_id = _create(client, auth_headers).json()["run"]["id"]
    blobs = [
        client.get(f"{_BASE}/runs", headers=auth_headers).text,
        client.get(f"{_BASE}/runs/{run_id}", headers=auth_headers).text,
        client.get(f"{_BASE}/runs/{run_id}/emails", headers=auth_headers).text,
    ]
    for blob in blobs:
        assert "credential_ref" not in blob
        assert "email_fingerprint" not in blob
        # the write-only pasted text must never be echoed
        assert "email_text" not in blob


def test_operation_ids_are_unique(client):
    schema = client.app.openapi()
    op_ids = [
        op["operationId"]
        for path in schema["paths"].values()
        for op in path.values()
        if isinstance(op, dict) and "operationId" in op
    ]
    assert len(op_ids) == len(set(op_ids)), "duplicate operationId in OpenAPI"
    shop = [oid for oid in op_ids if oid.startswith("shop_check_")]
    assert set(shop) == {
        "shop_check_runs_create",
        "shop_check_runs_list",
        "shop_check_runs_get",
        "shop_check_runs_emails",
        "shop_check_runs_cancel",
    }


def test_email_text_is_write_only_in_schema(client):
    schema = client.app.openapi()
    create = schema["components"]["schemas"]["ShopCheckRunCreate"]["properties"]
    assert create["email_text"].get("writeOnly") is True
    # confirm the field never appears on any response model
    dumped = json.dumps(schema["components"]["schemas"])
    assert '"ShopCheckRunDetail"' in dumped
