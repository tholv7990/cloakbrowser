"""Desktop sidecar entrypoint.

Frozen by PyInstaller and launched by the Tauri shell. Serves the FastAPI app on
the loopback port the shell chose; all config/secrets come from the environment the
shell injected: PLASMA_PORT, PLASMA_LOCAL_TOKEN, PLASMA_REQUIRE_LOCAL_TOKEN,
PLASMA_ALLOWED_ORIGIN, CLOAK_MANAGER_DATA_ROOT. Binds 127.0.0.1 only.
"""

from __future__ import annotations

import os

from .main import create_app


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PLASMA_PORT", "8765"))
    uvicorn.run(
        create_app,
        host="127.0.0.1",
        port=port,
        factory=True,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
