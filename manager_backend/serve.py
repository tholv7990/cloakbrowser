"""Desktop sidecar entrypoint.

Frozen by PyInstaller and launched by the Tauri shell. Serves the FastAPI app on
the loopback port the shell chose; all config/secrets come from the environment the
shell injected: PLASMA_PORT, PLASMA_LOCAL_TOKEN, PLASMA_REQUIRE_LOCAL_TOKEN,
PLASMA_ALLOWED_ORIGIN, CLOAK_MANAGER_DATA_ROOT. Binds 127.0.0.1 only.
"""

from __future__ import annotations

import os
import sys

# Absolute (not relative): PyInstaller freezes this file as the __main__ entry, which
# has no parent package, so `from .main` raises "attempted relative import with no known
# parent package". The spec bundles manager_backend as a package (pathex + submodules),
# so the absolute import resolves both frozen and via `python -m manager_backend.serve`.
from manager_backend.main import create_app


def _run_server() -> None:
    import uvicorn

    # A windowed frozen build has no console: sys.stdout/stderr are None, and
    # uvicorn's default log formatter calls sys.stdout.isatty() while configuring
    # logging ("Unable to configure formatter 'default'"). Give it real streams.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115 — process-lifetime
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115 — process-lifetime

    port = int(os.environ.get("PLASMA_PORT", "8765"))
    uvicorn.run(
        create_app,
        host="127.0.0.1",
        port=port,
        factory=True,
        log_level="warning",
    )


def main() -> None:
    # PyInstaller onefile IGNORES `-m <module>` and re-runs THIS frozen entry with the
    # original args still in sys.argv. The launcher spawns the Google seed via
    # `sys.executable -m manager_backend.features.runtime.google_seed <dir>`; under the
    # frozen exe that lands here, so route it to the seed instead of starting a second
    # uvicorn server (which crashes on the windowed child's None stdout). Under a real
    # interpreter `-m` runs the module directly and this branch never sees it.
    argv = sys.argv[1:]
    if len(argv) >= 3 and argv[0] == "-m" and argv[1].endswith(".google_seed"):
        from manager_backend.features.runtime.google_seed import seed

        try:
            seed(argv[2])
        except Exception:
            pass  # best-effort; search seeding must never fail a launch
        return
    _run_server()


if __name__ == "__main__":
    main()
