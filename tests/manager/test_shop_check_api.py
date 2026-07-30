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


def test_create_hands_the_run_to_the_coordinator(client, auth_headers):
    _setup(client)
    run_id = _create(client, auth_headers).json()["run"]["id"]
    # 202 means accepted-and-started: the created run goes straight to the
    # coordinator (inert here; test_shop_check_e2e.py drives the real one).
    assert client.app.state.shop_check_coordinator.started == [run_id]


def test_invalid_and_duplicate_lines_are_reported_with_line_and_mask(client, auth_headers):
    _setup(client)
    # line 3 duplicates line 1 (same local part, domain case only differs).
    text = "alice@example.com\nnot-an-email\nalice@Example.com\n"
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


def test_cleanup_rejected_while_run_is_active(client, auth_headers):
    # A freshly created run is queued (non-terminal); a direct cleanup call must
    # not be able to delete its profiles until it finishes or is cancelled.
    _setup(client)
    run_id = _create(client, auth_headers).json()["run"]["id"]
    response = client.post(
        f"{_BASE}/runs/{run_id}/cleanup",
        headers=auth_headers,
        json={"confirm": True, "expected_profile_count": 0},
    )
    assert response.status_code == 409


# --- validation secrecy (item 4) --------------------------------------------
# A Pydantic ValidationError carries the full offending input (the entire pasted
# email_text). These lock down that the global 422 handler never echoes it.
_SENTINEL = "do-not-leak-3f9a@secret-example.com"


def _assert_safe_422(response, sentinel):
    assert response.status_code == 422
    assert sentinel not in response.text
    body = response.json()
    # standard safe ErrorEnvelope, no raw input echoed
    assert set(body["error"]) == {"code", "message", "field_errors", "request_id"}
    assert body["error"]["code"] == "validation_error"


def test_over_limit_input_does_not_leak_email_text(client, auth_headers):
    lines = [_SENTINEL] + [f"user{i}@example.com" for i in range(1001)]
    response = _create(client, auth_headers, email_text="\n".join(lines))
    _assert_safe_422(response, _SENTINEL)


def test_authorization_failure_does_not_leak_email_text(client, auth_headers):
    response = _create(
        client, auth_headers, email_text=_SENTINEL, authorized_only_ack=False
    )
    _assert_safe_422(response, _SENTINEL)


def test_max_length_failure_does_not_leak_email_text(client, auth_headers):
    huge = _SENTINEL + "\n" + ("a" * 2_000_001)
    response = _create(client, auth_headers, email_text=huge)
    _assert_safe_422(response, _SENTINEL)


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


# --- input bounding (item 5) ------------------------------------------------
def test_exactly_1000_entries_accepted(client, auth_headers):
    _setup(client)
    text = "\n".join(f"user{i}@example.com" for i in range(1000))
    response = _create(client, auth_headers, email_text=text)
    assert response.status_code == 202
    assert response.json()["input_summary"]["valid"] == 1000


def test_1001_entries_rejected_before_persistence(client, auth_headers):
    _setup(client)
    text = "\n".join(f"user{i}@example.com" for i in range(1001))
    response = _create(client, auth_headers, email_text=text)
    assert response.status_code == 422
    # nothing persisted
    assert client.get(_BASE + "/runs", headers=auth_headers).json()["total"] == 0


def test_blank_lines_do_not_count_toward_limit(client, auth_headers):
    _setup(client)
    lines = [f"user{i}@example.com" for i in range(1000)]
    text = "\n\n".join(lines) + "\n\n\n"  # blanks interleaved
    response = _create(client, auth_headers, email_text=text)
    assert response.status_code == 202


def test_invalid_and_duplicate_previews_cap_at_100(client, auth_headers):
    _setup(client)
    invalid = "\n".join("bad-line" + str(i) for i in range(150))
    text = "keeper@example.com\n" + invalid
    summary = _create(client, auth_headers, email_text=text).json()["input_summary"]
    assert summary["invalid"] == 150  # accurate full count
    assert len(summary["invalid_entries"]) == 100  # capped preview
    assert summary["invalid_truncated"] is True

    dups = "\n".join(["dup@example.com"] * 151)
    text2 = "dup@example.com\n" + dups
    summary2 = _create(client, auth_headers, email_text=text2).json()["input_summary"]
    assert summary2["duplicates"] == 151
    assert len(summary2["duplicate_entries"]) == 100
    assert summary2["duplicate_truncated"] is True


# --- output_dir restriction (item 7) ----------------------------------------
def test_output_dir_is_not_accepted_on_create(client, auth_headers):
    _setup(client)
    response = client.post(
        f"{_BASE}/runs",
        headers=auth_headers,
        json=_valid_payload(output_dir="C:/Windows/Temp"),
    )
    assert response.status_code == 422  # extra field forbidden


def test_output_dir_absent_from_create_schema(client):
    schema = client.app.openapi()
    props = schema["components"]["schemas"]["ShopCheckRunCreate"]["properties"]
    assert "output_dir" not in props


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
        "shop_check_runs_export",
        "shop_check_runs_cancel",
        "shop_check_runs_cleanup",
    }


def test_email_text_is_write_only_in_schema(client):
    schema = client.app.openapi()
    create = schema["components"]["schemas"]["ShopCheckRunCreate"]["properties"]
    assert create["email_text"].get("writeOnly") is True
    assert '"ShopCheckRunDetail"' in json.dumps(schema["components"]["schemas"])
