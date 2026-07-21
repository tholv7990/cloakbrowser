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


class ManagerSettings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    data_root: Path = Field(default_factory=default_data_root)
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_origin: str = "http://127.0.0.1:5173"
    install_token: str | None = None
    max_concurrent_launches: int = Field(default=2, ge=1, le=8)

    @property
    def profile_root(self) -> Path:
        return self.data_root / "profiles"

    @property
    def token_path(self) -> Path:
        return self.data_root / "install-token"

    def resolved_install_token(self) -> str:
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
