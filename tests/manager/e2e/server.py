from __future__ import annotations

import os
from pathlib import Path

from manager_backend.config import ManagerSettings
from manager_backend.main import create_app


def create_e2e_app():
    data_root = os.environ.get("CLOAK_E2E_DATA_ROOT")
    origin = os.environ.get("CLOAK_E2E_ALLOWED_ORIGIN")
    if not data_root or not origin:
        raise RuntimeError("E2E server requires isolated data root and allowed origin")
    return create_app(
        ManagerSettings(
            data_root=Path(data_root),
            host="127.0.0.1",
            port=int(os.environ["CLOAK_E2E_BACKEND_PORT"]),
            allowed_origin=origin,
        )
    )
