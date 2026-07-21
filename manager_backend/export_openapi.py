from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .config import ManagerSettings
from .main import create_app


def main() -> None:
    output = Path(__file__).with_name("openapi.json")
    with tempfile.TemporaryDirectory(prefix="cloakbrowser-openapi-") as temporary:
        settings = ManagerSettings(
            data_root=Path(temporary),
            install_token="openapi-export-only",
        )
        app = create_app(settings)
        document = app.openapi()
        app.state.engine.dispose()
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
