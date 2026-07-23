"""Plasma cloud FastAPI application factory.

create_app() wires the tested service layer into HTTP routes. Secrets come from the
environment (load_settings) in production; tests inject settings + a SQLite session
factory + a recording email sender.
"""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from .config import CloudSettings, load_settings
from .db import create_engine_for, create_session_factory, database_url
from .email import ConsoleEmailSender, EmailSender
from .errors import install_error_handlers
from .features.activation.routes import router as activation_router
from .features.auth.routes import router as auth_router
from .features.devices.routes import router as devices_router
from .features.oauth.routes import router as oauth_router
from .features.updates.routes import router as updates_router


def create_app(
    settings: CloudSettings | None = None,
    *,
    session_factory: sessionmaker | None = None,
    email_sender: EmailSender | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="Plasma Cloud", version="1.0.0")
    app.state.settings = settings
    if session_factory is None:
        session_factory = create_session_factory(create_engine_for(database_url()))
    app.state.session_factory = session_factory
    app.state.email_sender = email_sender or ConsoleEmailSender()

    install_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(oauth_router)
    app.include_router(devices_router)
    app.include_router(activation_router)
    app.include_router(updates_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "plasma-cloud"}

    return app
