from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from manager_backend.features.diagnostics.targets import (
    TargetSnapshot,
    normalize_cloudflare,
)


pytestmark = [
    pytest.mark.manager_e2e,
    pytest.mark.skipif(os.name != "nt", reason="Windows Manager E2E only"),
]


def _wait_runtime(client, runtime_id: str, wanted: set[str], timeout: float = 45) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = client.get(f"/runtimes/{runtime_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["state"] in wanted:
            return last
        time.sleep(0.1)
    pytest.fail(f"runtime did not reach {sorted(wanted)}; last={last}")


@pytest.mark.skipif(
    os.environ.get("CLOAK_RUN_MANAGER_E2E") != "1",
    reason="set CLOAK_RUN_MANAGER_E2E=1 for deterministic Manager E2E",
)
def test_authenticated_windows_foundation_smoke(
    manager_stack,
    authenticated_client,
    disposable_profile,
    e2e_report,
):
    client = authenticated_client
    profile = disposable_profile
    original_seed = profile["fingerprint_seed"]
    original_updated = profile["updated_at"]

    e2e_report.step("frontend_ready")
    frontend = client.raw_get(manager_stack.frontend_url)
    assert frontend.status_code == 200
    assert "CloakBrowser" in frontend.text
    manager_stack.verify_ui_login()

    e2e_report.step("profile_partial_patch")
    patched = client.patch(
        f"/profiles/{profile['id']}",
        json={"expected_updated_at": original_updated, "notes": "e2e partial edit"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["notes"] == "e2e partial edit"
    assert patched.json()["fingerprint_seed"] == original_seed

    e2e_report.step("extension_register_assign")
    registered = client.post(
        "/extensions", json={"directory": str(manager_stack.extension_root)}
    )
    assert registered.status_code == 201, registered.text
    extension = registered.json()
    manager_stack.resources.track_extension(extension["id"])
    assigned = client.put(
        f"/profiles/{profile['id']}/extensions",
        json={"extension_ids": [extension["id"]]},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["extension_ids"] == [extension["id"]]

    e2e_report.step("cookie_roundtrip")
    fixture = Path("tests/fixtures/cookies/manager-e2e.json").read_text(encoding="utf-8")
    imported = client.post(
        f"/profiles/{profile['id']}/cookies/import",
        json={"format": "playwright", "content": fixture},
        timeout=60,
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported_count"] == 1
    exported_cookies = client.get(
        f"/profiles/{profile['id']}/cookies/export", timeout=60
    )
    assert exported_cookies.status_code == 200, exported_cookies.text
    cookies = exported_cookies.json()
    assert any(
        cookie["name"] == "manager_e2e" and cookie["domain"] == ".example.com"
        for cookie in cookies
    )

    e2e_report.step("real_browser_launch")
    started = client.post(f"/profiles/{profile['id']}/start")
    assert started.status_code == 202, started.text
    runtime_id = started.json()["id"]
    manager_stack.resources.runtime_ids.append(runtime_id)
    running = _wait_runtime(client, runtime_id, {"running", "crashed"})
    assert running["state"] == "running", running["last_message"]
    assert client.get("/app/bootstrap").json()["running_session_count"] == 1
    assert manager_stack.wait_for_runtime_websocket(client, runtime_id) == "running"
    assert manager_stack.runtime_has_extension(profile["id"], manager_stack.extension_root)

    logs = client.get(f"/profiles/{profile['id']}/logs")
    assert logs.status_code == 200, logs.text
    events = {item["event"] for item in logs.json()["items"]}
    assert {"runtime.start_requested", "runtime.ready"} <= events

    e2e_report.step("real_browser_stop")
    stopped = client.post(f"/profiles/{profile['id']}/stop")
    assert stopped.status_code == 202, stopped.text
    final_runtime = _wait_runtime(client, runtime_id, {"stopped", "crashed"})
    assert final_runtime["state"] == "stopped", final_runtime["last_message"]
    assert client.get("/app/bootstrap").json()["running_session_count"] == 0

    e2e_report.step("profile_export_import")
    exported_profile = client.get(f"/profiles/{profile['id']}/export")
    assert exported_profile.status_code == 200, exported_profile.text
    imported_profile = client.post(
        "/profiles/import",
        content=exported_profile.content,
        headers={"Content-Type": "application/json"},
    )
    assert imported_profile.status_code == 201, imported_profile.text
    copy_id = imported_profile.json()["profile_id"]
    manager_stack.resources.track_profile(copy_id)
    copied = client.get(f"/profiles/{copy_id}").json()
    assert copied["id"] != profile["id"]
    assert copied["fingerprint_seed"] != original_seed
    assert copied["notes"] == "e2e partial edit"

    e2e_report.step("local_diagnostic_and_containment")
    diagnostic = normalize_cloudflare(
        TargetSnapshot(
            page_loaded=True,
            signals={"managed_challenge": False, "user_interaction_required": False},
        )
    )
    assert diagnostic.status == "passed"
    profile_directory = Path(profile["profile_directory"]).resolve()
    assert manager_stack.data_root.resolve() in profile_directory.parents
    report_json, report_markdown = e2e_report.write()
    assert manager_stack.report_root.resolve() in report_json.resolve().parents
    assert manager_stack.report_root.resolve() in report_markdown.resolve().parents


@pytest.mark.manager_e2e_existing_owner
@pytest.mark.skipif(
    os.environ.get("CLOAK_RUN_MANAGER_EXISTING_OWNER_E2E") != "1",
    reason="set CLOAK_RUN_MANAGER_EXISTING_OWNER_E2E=1 for existing-owner E2E",
)
def test_existing_owner_mode_uses_environment_credentials_only(existing_owner_client):
    session = existing_owner_client.get("/auth/session")
    assert session.status_code == 200
    assert set(session.json()) == {"email", "csrf_token"}
