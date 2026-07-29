"""Prove sanitize_error is used by PRODUCTION paths, not just unit-tested.

Covers both directions of item 1: the persist helpers sanitize before writing,
and the read/serialization layer sanitizes again (defense in depth) so a raw
error that somehow reached a column never leaks through the API.
"""

from __future__ import annotations

from manager_backend.features.proxies.credentials import MemoryCredentialStore
from manager_backend.features.shop_check import service
from manager_backend.models import ShopCheckRun, ShopCheckWorker

EMAIL_SENTINEL = "leak.target@corp-example.com"
PROXY_URL_SENTINEL = "socks5h://puser:PxPass123@global.711proxy.com:20000"
HOSTPORT_SENTINEL = "203.0.113.9:20000:puser:PxPass123"
RAW_PASSWORD = "PxPass123"


def _make_run(client) -> str:
    client.app.state.credential_store = MemoryCredentialStore()
    body = {
        "email_text": "a@example.com\nb@example.com",
        "emails_per_profile": 5,
        "max_parallel": 3,
        "authorized_only_ack": True,
    }
    resp = client.post(
        "/api/v1/automations/shop-check/runs",
        headers=_auth(client),
        json=body,
    )
    return resp.json()["run"]["id"]


_HEADERS: dict = {}


def _auth(client):
    return _HEADERS


def test_run_detail_api_sanitizes_persisted_errors(client, auth_headers):
    global _HEADERS
    _HEADERS = auth_headers
    run_id = _make_run(client)

    # Simulate a raw error slipping straight into the columns (bypassing helpers).
    dirty = f"boom {EMAIL_SENTINEL} via {PROXY_URL_SENTINEL} and {HOSTPORT_SENTINEL}"
    with client.app.state.session_factory() as session:
        run = session.get(ShopCheckRun, run_id)
        run.error = dirty
        session.add(ShopCheckWorker(run_id=run_id, ordinal=0, state="terminal", error=dirty))
        session.commit()

    blob = client.get(
        f"/api/v1/automations/shop-check/runs/{run_id}", headers=auth_headers
    ).text
    # Serialization defense scrubs everything, even a raw column value.
    assert EMAIL_SENTINEL not in blob
    assert "PxPass123" not in blob
    assert "puser" not in blob
    assert "credential_ref" not in blob


def test_persist_helpers_sanitize_before_writing(db_session_factory):
    with db_session_factory() as session:
        run = ShopCheckRun(
            status="queued", emails_per_profile=5, max_parallel=3,
            target_url="https://shop.app/", total_emails=0,
        )
        session.add(run)
        session.flush()
        service.set_run_error(
            run, f"failed {EMAIL_SENTINEL} {PROXY_URL_SENTINEL}", RAW_PASSWORD
        )
        worker = ShopCheckWorker(run_id=run.id, ordinal=0, state="pending")
        session.add(worker)
        session.flush()
        service.set_worker_error(worker, f"dead {HOSTPORT_SENTINEL}", RAW_PASSWORD)
        session.commit()

        assert EMAIL_SENTINEL not in run.error
        assert RAW_PASSWORD not in run.error
        assert RAW_PASSWORD not in worker.error
        assert "puser" not in worker.error
