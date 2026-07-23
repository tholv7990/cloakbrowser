from __future__ import annotations

import os
import secrets
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


def default_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    return Path(local_app_data) / "CloakBrowser" / "Manager"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


class ManagerSettings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    data_root: Path = Field(default_factory=default_data_root)
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_origin: str = "http://127.0.0.1:5273"
    install_token: str | None = None
    # When true, every /api/v1 request must also carry a valid local Bearer token
    # (the desktop shell injects it). Off by default so the browser dev workflow is
    # unchanged; packaged builds set PLASMA_REQUIRE_LOCAL_TOKEN=1.
    require_local_token: bool = Field(
        default_factory=lambda: _env_flag("PLASMA_REQUIRE_LOCAL_TOKEN")
    )
    auto_backup_enabled: bool = True
    max_concurrent_launches: int = Field(default=2, ge=1, le=8)
    max_concurrent_diagnostics: int = Field(default=2, ge=1, le=8)
    diagnostic_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    diagnostic_cleanup_wait_seconds: float = Field(default=0.25, gt=0, le=5)
    diagnostic_shutdown_cleanup_wait_seconds: float = Field(
        default=2.0, gt=0, le=30
    )
    diagnostic_max_report_bytes: int = Field(
        default=1024 * 1024, ge=1024, le=10 * 1024 * 1024
    )
    diagnostic_max_screenshot_bytes: int = Field(
        default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024
    )

    @property
    def profile_root(self) -> Path:
        return self.data_root / "profiles"

    @property
    def token_path(self) -> Path:
        return self.data_root / "install-token"

    def resolved_install_token(self) -> str:
        # A per-process token (injected by the desktop shell) wins over the persisted
        # install-token file, so a token read from disk can't outlive the process.
        per_process = os.environ.get("PLASMA_LOCAL_TOKEN")
        if per_process:
            return per_process
        if self.install_token:
            return self.install_token
        return load_or_create_install_token(self.token_path)


def load_or_create_install_token(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    if existing:
        return existing

    token = secrets.token_urlsafe(32)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(token, encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return token
