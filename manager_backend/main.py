from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import ManagerSettings
from .errors import install_error_handlers
from .security import require_local_token


def create_app(settings: ManagerSettings | None = None) -> FastAPI:
    resolved = settings or ManagerSettings()
    if resolved.host != "127.0.0.1":
        raise ValueError("CloakBrowser Manager must bind to 127.0.0.1")

    app = FastAPI(title="CloakBrowser Manager API", version="1.0.0")
    app.state.settings = resolved
    app.state.install_token = resolved.resolved_install_token()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved.allowed_origin],
        allow_credentials=False,
        allow_methods=["*"] ,
        allow_headers=["Authorization", "Content-Type"],
    )
    install_error_handlers(app)

    @app.get("/api/v1/health", dependencies=[Depends(require_local_token)])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "cloakbrowser-manager",
            "api_version": "v1",
        }

    return app
