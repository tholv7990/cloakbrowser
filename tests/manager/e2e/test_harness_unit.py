from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.manager.e2e.harness import (
    E2ECredentials,
    ManagedProcess,
    OwnedResources,
    existing_owner_credentials,
    reserve_loopback_port,
    resolve_owned_path,
    wait_for_http,
)
from tests.manager.e2e.reporting import redact, write_report


def test_existing_owner_credentials_are_environment_only(monkeypatch):
    monkeypatch.setenv("CLOAK_MANAGER_EMAIL", "owner@example.test")
    monkeypatch.setenv("CLOAK_MANAGER_PASSWORD", "not-written-anywhere")

    credentials = existing_owner_credentials()

    assert credentials == E2ECredentials("owner@example.test", "not-written-anywhere")
    assert "not-written-anywhere" not in repr(credentials)


@pytest.mark.parametrize(
    ("missing", "reason"),
    [
        ({"CLOAK_MANAGER_EMAIL"}, "missing CLOAK_MANAGER_EMAIL"),
        ({"CLOAK_MANAGER_PASSWORD"}, "missing CLOAK_MANAGER_PASSWORD"),
        (
            {"CLOAK_MANAGER_EMAIL", "CLOAK_MANAGER_PASSWORD"},
            "missing CLOAK_MANAGER_EMAIL and CLOAK_MANAGER_PASSWORD",
        ),
    ],
)
def test_existing_owner_credentials_has_exact_safe_missing_reason(monkeypatch, missing, reason):
    values = {
        "CLOAK_MANAGER_EMAIL": "owner@example.test",
        "CLOAK_MANAGER_PASSWORD": "secret-value",
    }
    for name, value in values.items():
        if name in missing:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)

    with pytest.raises(pytest.skip.Exception, match=f"^{reason}$"):
        existing_owner_credentials()


def test_reserve_loopback_port_returns_bindable_local_port():
    port = reserve_loopback_port()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def test_report_redaction_is_recursive_and_does_not_mutate_source():
    source = {
        "email": "owner@example.test",
        "csrf_token": "csrf-secret",
        "nested": [{"password": "password-secret", "status": "passed"}],
        "cookie": "session-secret",
        "license": "license-secret",
    }

    result = redact(source)

    assert result == {
        "email": "[redacted]",
        "csrf_token": "[redacted]",
        "nested": [{"password": "[redacted]", "status": "passed"}],
        "cookie": "[redacted]",
        "license": "[redacted]",
    }
    assert source["csrf_token"] == "csrf-secret"


def test_report_writer_scrubs_secret_values_even_under_safe_keys(tmp_path):
    json_path, markdown_path = write_report(
        tmp_path,
        {
            "steps": [{"name": "failure", "status": "secret-in-error"}],
            "message": "prefix secret-in-error suffix",
        },
        secrets=["secret-in-error"],
    )
    combined = json_path.read_text(encoding="utf-8") + markdown_path.read_text(
        encoding="utf-8"
    )
    assert "secret-in-error" not in combined


def test_owned_resource_tracker_deduplicates_and_preserves_creation_order():
    resources = OwnedResources()
    resources.track_profile("profile-1")
    resources.track_profile("profile-1")
    resources.track_profile("profile-2")
    resources.track_extension("extension-1")

    assert resources.profile_ids == ["profile-1", "profile-2"]
    assert resources.extension_ids == ["extension-1"]


def test_owned_path_resolution_rejects_sibling_escape(tmp_path):
    owned_root = tmp_path / "owned"
    owned_root.mkdir()
    assert resolve_owned_path(owned_root, owned_root / "child") == (
        owned_root / "child"
    ).resolve()
    with pytest.raises(ValueError, match="outside suite-owned root"):
        resolve_owned_path(owned_root, tmp_path / "sibling")


def test_license_is_never_copied_into_report_environment(monkeypatch):
    monkeypatch.setenv("CLOAKBROWSER_LICENSE_KEY", "license-secret")
    resources = OwnedResources()
    report = redact(resources.report_metadata())
    assert "license-secret" not in repr(report)
    assert os.environ["CLOAKBROWSER_LICENSE_KEY"] == "license-secret"


def test_wait_for_http_uses_condition_readiness_not_a_fixed_sleep():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ready")

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        wait_for_http(f"http://127.0.0.1:{server.server_port}/", timeout=2)
    finally:
        server.shutdown()
        server.server_close()


def test_managed_process_terminates_only_its_owned_process():
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    owned = ManagedProcess(child, "unit-child")
    owned.close(timeout=2)
    assert child.poll() is not None


@pytest.mark.skipif(os.name != "nt", reason="PowerShell runner is Windows-only")
@pytest.mark.parametrize(
    ("mode", "live_switch", "expected_child"),
    [
        (
            "Deterministic",
            False,
            {
                "CLOAK_RUN_MANAGER_E2E": "1",
                "CLOAK_RUN_MANAGER_EXISTING_OWNER_E2E": "",
                "CLOAK_LIVE_DIAGNOSTICS": "",
            },
        ),
        (
            "Deterministic",
            True,
            {
                "CLOAK_RUN_MANAGER_E2E": "1",
                "CLOAK_RUN_MANAGER_EXISTING_OWNER_E2E": "",
                "CLOAK_LIVE_DIAGNOSTICS": "1",
            },
        ),
        (
            "ExistingOwner",
            False,
            {
                "CLOAK_RUN_MANAGER_E2E": "",
                "CLOAK_RUN_MANAGER_EXISTING_OWNER_E2E": "1",
                "CLOAK_LIVE_DIAGNOSTICS": "",
            },
        ),
    ],
)
def test_powershell_runner_scopes_and_restores_flags_on_failure(
    tmp_path, mode, live_switch, expected_child
):
    stub = tmp_path / "python.cmd"
    names = (
        "CLOAK_RUN_MANAGER_E2E",
        "CLOAK_RUN_MANAGER_EXISTING_OWNER_E2E",
        "CLOAK_LIVE_DIAGNOSTICS",
    )
    stub.write_text(
        "@echo off\n"
        + "\n".join(f"echo CHILD_{name}=[%{name}%]" for name in names)
        + "\nexit /b 9\n",
        encoding="utf-8",
    )
    script = Path("scripts/run_manager_e2e.ps1").resolve()
    switch = " -LiveDiagnostics" if live_switch else ""
    command = (
        f"try {{ & '{script}' -Mode {mode}{switch} }} catch {{ Write-Output 'CAUGHT' }}; "
        + "; ".join(
            f"Write-Output ('AFTER_{name}=[' + $env:{name} + ']')" for name in names
        )
    )
    environment = dict(os.environ)
    environment["PATH"] = f"{tmp_path}{os.pathsep}{environment['PATH']}"
    environment["CLOAKBROWSER_LICENSE_KEY"] = "fixture-license"
    original = {
        "CLOAK_RUN_MANAGER_E2E": "original-deterministic",
        "CLOAK_RUN_MANAGER_EXISTING_OWNER_E2E": "original-existing",
        "CLOAK_LIVE_DIAGNOSTICS": "stale-live",
    }
    environment.update(original)

    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=Path.cwd(),
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    assert "CAUGHT" in completed.stdout
    for name, expected in expected_child.items():
        assert f"CHILD_{name}=[{expected}]" in completed.stdout
    for name, expected in original.items():
        assert f"AFTER_{name}=[{expected}]" in completed.stdout


@pytest.mark.skipif(os.name != "nt", reason="PowerShell runner is Windows-only")
def test_powershell_runner_restores_originally_absent_flags(tmp_path):
    stub = tmp_path / "python.cmd"
    stub.write_text("@echo off\nexit /b 9\n", encoding="utf-8")
    script = Path("scripts/run_manager_e2e.ps1").resolve()
    names = (
        "CLOAK_RUN_MANAGER_E2E",
        "CLOAK_RUN_MANAGER_EXISTING_OWNER_E2E",
        "CLOAK_LIVE_DIAGNOSTICS",
    )
    checks = "; ".join(
        f"Write-Output ('AFTER_{name}_PRESENT=' + (Test-Path Env:{name}))"
        for name in names
    )
    command = (
        f"try {{ & '{script}' -Mode Deterministic }} catch {{ Write-Output 'CAUGHT' }}; "
        + checks
    )
    environment = dict(os.environ)
    environment["PATH"] = f"{tmp_path}{os.pathsep}{environment['PATH']}"
    environment["CLOAKBROWSER_LICENSE_KEY"] = "fixture-license"
    for name in names:
        environment.pop(name, None)

    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        cwd=Path.cwd(),
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    assert "CAUGHT" in completed.stdout
    for name in names:
        assert f"AFTER_{name}_PRESENT=False" in completed.stdout
