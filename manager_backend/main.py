from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .auth.routes import router as auth_router
from .config import ManagerSettings
from .db import create_engine_for, create_session_factory
from .errors import install_error_handlers
from .models import Base
from .dependencies import require_authenticated_session


def create_app(settings: ManagerSettings | None = None) -> FastAPI:
    resolved = settings or ManagerSettings()
    if resolved.host != "127.0.0.1":
        raise ValueError("CloakBrowser Manager must bind to 127.0.0.1")

    app = FastAPI(title="CloakBrowser Manager API", version="1.0.0")
    app.state.settings = resolved
    app.state.install_token = resolved.resolved_install_token()
    app.state.engine = create_engine_for(resolved)
    Base.metadata.create_all(app.state.engine)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.login_failures = {}
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved.allowed_origin],
        allow_credentials=True,
        allow_methods=["*"] ,
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )
    install_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(api_router)

    @app.get("/api/v1/health", dependencies=[Depends(require_authenticated_session)])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "cloakbrowser-manager",
            "api_version": "v1",
        }

    return app
