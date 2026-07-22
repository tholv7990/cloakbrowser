from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import psutil
import pytest

from cloakbrowser.config import get_binary_path

from .reporting import write_report


@dataclass(frozen=True, repr=False)
class E2ECredentials:
    email: str
    password: str

    def __repr__(self) -> str:
        return "E2ECredentials(email='[redacted]', password='[redacted]')"


def existing_owner_credentials() -> E2ECredentials:
    email = os.environ.get("CLOAK_MANAGER_EMAIL")
    password = os.environ.get("CLOAK_MANAGER_PASSWORD")
    missing = [
        name
        for name, value in (
            ("CLOAK_MANAGER_EMAIL", email),
            ("CLOAK_MANAGER_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        joined = " and ".join(missing)
        pytest.skip(f"missing {joined}")
    return E2ECredentials(email=email, password=password)  # type: ignore[arg-type]


def reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_http(url: str, *, timeout: float, expected_status: int = 200) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=min(1.0, timeout))
            if response.status_code == expected_status:
                return
            last_error = RuntimeError(f"unexpected readiness status {response.status_code}")
        except (httpx.HTTPError, OSError) as error:
            last_error = error
        time.sleep(0.05)
    raise TimeoutError(f"service did not become ready: {type(last_error).__name__}")


class ManagedProcess:
    def __init__(self, process: subprocess.Popen[bytes], label: str):
        self.process = process
        self.label = label
        try:
            self._created_at = psutil.Process(process.pid).create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._created_at = None

    def close(self, *, timeout: float = 10.0) -> None:
        if self.process.poll() is not None:
            return
        try:
            owner = psutil.Process(self.process.pid)
            if self._created_at is None or owner.create_time() != self._created_at:
                return
            descendants = owner.children(recursive=True)
            for child in descendants:
                child.terminate()
            owner.terminate()
            _gone, alive = psutil.wait_procs([*descendants, owner], timeout=timeout)
            for process in alive:
                process.kill()
            if alive:
                psutil.wait_procs(alive, timeout=min(timeout, 5.0))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def resolve_owned_path(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve(strict=True)
    resolved_candidate = candidate.resolve(strict=False)
    if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
        raise ValueError("path is outside suite-owned root")
    return resolved_candidate


@dataclass
class OwnedResources:
    profile_ids: list[str] = field(default_factory=list)
    extension_ids: list[str] = field(default_factory=list)
    runtime_ids: list[str] = field(default_factory=list)

    @staticmethod
    def _track(collection: list[str], resource_id: str) -> None:
        if resource_id not in collection:
            collection.append(resource_id)

    def track_profile(self, profile_id: str) -> None:
        self._track(self.profile_ids, profile_id)

    def track_extension(self, extension_id: str) -> None:
        self._track(self.extension_ids, extension_id)

    def report_metadata(self) -> dict[str, object]:
        return {
            "profile_ids": list(self.profile_ids),
            "extension_ids": list(self.extension_ids),
            "runtime_ids": list(self.runtime_ids),
        }


class AuthenticatedApiClient:
    def __init__(self, base_url: str, origin: str):
        self.origin = origin
        self._client = httpx.Client(base_url=f"{base_url}/api/v1", timeout=15)
        self.csrf_token: str | None = None

    def close(self) -> None:
        self._client.close()

    def _headers(self, mutation: bool, headers: dict[str, str] | None) -> dict[str, str]:
        result = dict(headers or {})
        if mutation:
            result.setdefault("Origin", self.origin)
            if self.csrf_token:
                result.setdefault("X-CSRF-Token", self.csrf_token)
        return result

    def request(self, method: str, path: str, **kwargs):
        mutation = method.upper() not in {"GET", "HEAD", "OPTIONS"}
        kwargs["headers"] = self._headers(mutation, kwargs.pop("headers", None))
        return self._client.request(method, path, **kwargs)

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs):
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs):
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.request("DELETE", path, **kwargs)

    def raw_get(self, url: str, **kwargs):
        return httpx.get(url, **kwargs)

    def session_cookie(self) -> str:
        value = self._client.cookies.get("cloak_session")
        if not value:
            raise RuntimeError("authenticated session cookie is unavailable")
        return value

    def setup(self, credentials: E2ECredentials) -> None:
        response = self.request(
            "POST",
            "/auth/setup",
            json={"email": credentials.email, "password": credentials.password},
        )
        response.raise_for_status()
        self.csrf_token = response.json()["csrf_token"]

    def logout(self) -> None:
        response = self.post("/auth/logout")
        response.raise_for_status()
        self.csrf_token = None

    def login(self, credentials: E2ECredentials) -> None:
        response = self.request(
            "POST",
            "/auth/login",
            json={"email": credentials.email, "password": credentials.password},
        )
        response.raise_for_status()
        self.csrf_token = response.json()["csrf_token"]


@dataclass
class E2EReport:
    report_root: Path
    metadata: dict[str, object]
    steps: list[dict[str, object]] = field(default_factory=list)

    def step(self, name: str, status: str = "passed") -> None:
        self.steps.append({"name": name, "status": status})

    def write(self) -> tuple[Path, Path]:
        return write_report(
            self.report_root,
            {**self.metadata, "steps": list(self.steps)},
        )


@dataclass
class ManagerStack:
    data_root: Path
    report_root: Path
    extension_root: Path
    backend_url: str
    frontend_url: str
    origin: str
    credentials: E2ECredentials
    backend: ManagedProcess
    frontend: ManagedProcess
    resources: OwnedResources = field(default_factory=OwnedResources)
    cleanup_client: AuthenticatedApiClient | None = None
    report: E2EReport | None = None

    def verify_ui_login(self) -> None:
        import cloakbrowser

        ui_root = resolve_owned_path(self.data_root, self.data_root / "ui-login")
        context = cloakbrowser.launch_persistent_context(str(ui_root), headless=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(self.frontend_url, wait_until="domcontentloaded", timeout=30_000)
            page.locator('input[type="email"]').fill(self.credentials.email)
            page.locator('input[type="password"]').fill(self.credentials.password)
            page.locator('button[type="submit"]').click()
            page.get_by_text("Profiles", exact=True).first.wait_for(timeout=30_000)
        finally:
            context.close()

    def runtime_has_extension(self, profile_id: str, extension_root: Path) -> bool:
        profile_marker = str(self.data_root / "profiles" / profile_id / "user-data").casefold()
        extension_marker = str(extension_root).casefold()
        try:
            root = psutil.Process(self.backend.process.pid)
            processes = root.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
        for process in processes:
            try:
                command = " ".join(process.cmdline()).casefold()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            if profile_marker in command and extension_marker in command:
                return True
        return False

    def wait_for_runtime_websocket(
        self,
        client: AuthenticatedApiClient,
        runtime_id: str,
        *,
        timeout: float = 10.0,
    ) -> str:
        from websockets.sync.client import connect

        uri = self.backend_url.replace("http://", "ws://") + "/api/v1/events"
        deadline = time.monotonic() + timeout
        with connect(
            uri,
            origin=self.origin,
            additional_headers={"Cookie": f"cloak_session={client.session_cookie()}"},
            open_timeout=timeout,
            close_timeout=2,
        ) as websocket:
            while time.monotonic() < deadline:
                message = json.loads(websocket.recv(timeout=max(0.1, deadline - time.monotonic())))
                if message.get("type") != "runtime.snapshot":
                    continue
                for runtime in message.get("runtimes", []):
                    if runtime.get("id") == runtime_id:
                        return str(runtime.get("state"))
        raise TimeoutError("runtime WebSocket state was not observed")

    def cleanup(self, client: AuthenticatedApiClient | None) -> None:
        cleanup_status = "passed"
        if client is not None:
            for profile_id in reversed(self.resources.profile_ids):
                try:
                    client.post(f"/profiles/{profile_id}/stop")
                except Exception:
                    cleanup_status = "warning"
            for extension_id in reversed(self.resources.extension_ids):
                try:
                    client.delete(f"/extensions/{extension_id}")
                except Exception:
                    cleanup_status = "warning"
            for profile_id in reversed(self.resources.profile_ids):
                try:
                    client.post(f"/profiles/{profile_id}/move-to-trash")
                except Exception:
                    cleanup_status = "warning"
            client.close()
        self.frontend.close()
        self.backend.close()
        owned = resolve_owned_path(self.data_root.parent, self.data_root)
        if owned.exists():
            shutil.rmtree(owned)
        extension = resolve_owned_path(self.report_root, self.extension_root)
        if extension.exists():
            shutil.rmtree(extension)
        if self.report is not None:
            self.report.metadata["resources"] = self.resources.report_metadata()
            self.report.metadata["cleanup_status"] = cleanup_status
            self.report.write()


def start_manager_stack(tmp_root: Path, report_root: Path) -> ManagerStack:
    binary = get_binary_path()
    if not binary.is_file():
        pytest.fail("installed CloakBrowser binary is unavailable")
    if not os.environ.get("CLOAKBROWSER_LICENSE_KEY"):
        pytest.fail("CLOAKBROWSER_LICENSE_KEY is missing from the E2E process environment")

    backend_port = reserve_loopback_port()
    frontend_port = reserve_loopback_port()
    backend_url = f"http://127.0.0.1:{backend_port}"
    frontend_url = f"http://127.0.0.1:{frontend_port}"
    data_root = tmp_root / "manager-data"
    data_root.mkdir(parents=True)
    extension_root = report_root / "fixture-extension"
    report_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(Path("tests/fixtures/extensions/manager-e2e"), extension_root)
    credentials = E2ECredentials(
        email=f"e2e-{os.getpid()}@example.com",
        password=f"E2E-{secrets.token_urlsafe(24)}!",
    )
    child_env = dict(os.environ)
    child_env.update(
        {
            "CLOAK_E2E_DATA_ROOT": str(data_root),
            "CLOAK_E2E_ALLOWED_ORIGIN": frontend_url,
            "CLOAK_E2E_BACKEND_PORT": str(backend_port),
            "VITE_API_MODE": "real",
            "VITE_API_BASE_URL": f"{backend_url}/api/v1",
            "VITE_WS_URL": f"ws://127.0.0.1:{backend_port}/api/v1/events",
        }
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    backend_process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.manager.e2e.server:create_e2e_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(backend_port),
            "--no-access-log",
        ],
        cwd=Path.cwd(),
        env=child_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    backend = ManagedProcess(backend_process, "manager-backend")
    frontend = None
    try:
        wait_for_http(f"{backend_url}/api/v1/auth/status", timeout=30)
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm:
            raise RuntimeError("npm is unavailable")
        frontend_process = subprocess.Popen(
            [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(frontend_port)],
            cwd=Path("manager/frontend"),
            env=child_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        frontend = ManagedProcess(frontend_process, "manager-frontend")
        wait_for_http(frontend_url, timeout=30)
        return ManagerStack(
            data_root=data_root,
            report_root=report_root,
            extension_root=extension_root,
            backend_url=backend_url,
            frontend_url=frontend_url,
            origin=frontend_url,
            credentials=credentials,
            backend=backend,
            frontend=frontend,
        )
    except Exception:
        if frontend is not None:
            frontend.close()
        backend.close()
        raise
