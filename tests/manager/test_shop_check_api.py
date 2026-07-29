from __future__ import annotations

import json

from manager_backend.features.proxies.credentials import MemoryCredentialStore

_BASE = "/api/v1/automations/shop-check"


def _setup(client) -> MemoryCredentialStore:
    store = MemoryCredentialStore()
    client.app.state.credential_store = store
    return store


def _valid_payload(**overrides) -> dict:
    payload = {
        "email_text": "alice@example.com\nbob@example.com",
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
def test_create_consumes_email_text_and_reports_summary(client, auth_headers):
    _setup(client)
    response = _create(client, auth_headers)
    assert response.status_code == 202, response.text
    body = response.json()
    assert set(body) == {"run", "input_summary"}
    summary = body["input_summary"]
    assert summary["valid"] == 2
    assert summary["duplicates"] == 0
    assert summary["invalid"] == 0
    assert summary["worker_count"] == 1
    assert body["run"]["total_emails"] == 2
    assert body["run"]["status"] == "queued"


def test_invalid_and_duplicate_lines_are_reported_with_line_and_mask(client, auth_headers):
    _setup(client)
    text = "alice@example.com\nnot-an-email\nAlice@example.com\n"
    response = _create(client, auth_headers, email_text=text)
    summary = response.json()["input_summary"]
    assert summary["valid"] == 1
    assert summary["duplicates"] == 1
    assert summary["invalid"] == 1
    invalid = summary["invalid_entries"][0]
    assert invalid["line"] == 2
    assert "not-an-email" not in invalid["masked"]
    dup = summary["duplicate_entries"][0]
    assert dup["line"] == 3


def test_create_with_no_valid_emails_is_400(client, auth_headers):
    _setup(client)
    response = _create(client, auth_headers, email_text="nope\n@bad\n")
    assert response.status_code == 400


def test_create_rejects_extra_field(client, auth_headers):
    _setup(client)
    response = client.post(
        f"{_BASE}/runs", headers=auth_headers, json=_valid_payload(smuggled="x")
    )
    assert response.status_code == 422


def test_create_requires_authorization_ack(client, auth_headers):
    _setup(client)
    assert _create(client, auth_headers, authorized_only_ack=False).status_code == 422


def test_create_rejects_out_of_range_and_bad_region(client, auth_headers):
    _setup(client)
    assert _create(client, auth_headers, emails_per_profile=6).status_code == 422
    assert _create(client, auth_headers, region="USA").status_code == 422


def test_requires_authenticated_session(client):
    response = client.post(
        f"{_BASE}/runs",
        headers={"Origin": "http://127.0.0.1:5173", "X-CSRF-Token": "nope"},
        json=_valid_payload(),
    )
    assert response.status_code in (401, 403)


def test_run_history_is_paginated(client, auth_headers):
    _setup(client)
    run_id = _create(client, auth_headers).json()["run"]["id"]
    listing = client.get(f"{_BASE}/runs", headers=auth_headers)
    assert listing.status_code == 200
    body = listing.json()
    assert set(body) == {"items", "total", "page", "page_size", "pages"}
    assert run_id in [r["id"] for r in body["items"]]


def test_get_missing_run_is_404(client, auth_headers):
    assert client.get(f"{_BASE}/runs/nope", headers=auth_headers).status_code == 404


def test_emails_endpoint_page_shape_and_typed_filter(client, auth_headers):
    _setup(client)
    run_id = _create(client, auth_headers).json()["run"]["id"]
    ok = client.get(f"{_BASE}/runs/{run_id}/emails", headers=auth_headers)
    assert ok.status_code == 200
    assert set(ok.json()) == {"items", "total", "page", "page_size", "pages"}
    # a filter value outside EmailResult is rejected by the typed query param
    bad = client.get(
        f"{_BASE}/runs/{run_id}/emails?result=not_a_result", headers=auth_headers
    )
    assert bad.status_code == 422
    good = client.get(
        f"{_BASE}/runs/{run_id}/emails?result=phone_otp_required", headers=auth_headers
    )
    assert good.status_code == 200


def test_cancel_run(client, auth_headers):
    _setup(client)
    run_id = _create(client, auth_headers).json()["run"]["id"]
    response = client.post(f"{_BASE}/runs/{run_id}/cancel", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


# --- security ---------------------------------------------------------------
def test_full_email_never_appears_in_any_response(client, auth_headers):
    _setup(client)
    sentinel = "sentinel.person@corp-example.com"
    run_id = _create(client, auth_headers, email_text=sentinel).json()["run"]["id"]
    blobs = [
        client.get(f"{_BASE}/runs", headers=auth_headers).text,
        client.get(f"{_BASE}/runs/{run_id}", headers=auth_headers).text,
        client.get(f"{_BASE}/runs/{run_id}/emails", headers=auth_headers).text,
    ]
    for blob in blobs:
        assert sentinel not in blob
        assert "credential_ref" not in blob
        assert "email_fingerprint" not in blob
        assert "email_text" not in blob


def test_operation_ids_are_unique(client):
    schema = client.app.openapi()
    op_ids = [
        op["operationId"]
        for path in schema["paths"].values()
        for op in path.values()
        if isinstance(op, dict) and "operationId" in op
    ]
    assert len(op_ids) == len(set(op_ids))
    shop = {oid for oid in op_ids if oid.startswith("shop_check_")}
    assert shop == {
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
    assert '"ShopCheckRunDetail"' in json.dumps(schema["components"]["schemas"])
