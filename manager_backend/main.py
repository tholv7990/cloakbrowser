from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .auth.routes import router as auth_router
from .config import ManagerSettings
from .db import create_engine_for, create_session_factory
from .errors import install_error_handlers
from .models import Base
from .dependencies import require_authenticated_session
from .features.runtime.manager import RuntimeManager
from .features.runtime.reconcile import cleanup_stale_locks, reconcile_runtimes
from .features.runtime.routes import runtime_to_dict
from .features.runtime.service import count_active_runtimes
from .auth.sessions import validate_session
from .dependencies import SESSION_COOKIE
from .models import RuntimeSession
from .features.proxies.credentials import KeyringCredentialStore
from .features.proxies.testing import ScannerQuickTester
from .features.proxies.service import build_proxy_preflight
from .features.proxies.quality import ProxyQualityManager, recover_orphan_quality_runs
from .features.portability.browser_cookies import CookieContextAdapter
from .features.settings.store import SettingsStore
from .features.diagnostics.service import DiagnosticManager
from .features.diagnostics.runner import (
    BrowserAdapter,
    DiagnosticRunner,
    ProxyPreflightResult,
    TargetAdapter,
)
from .features.diagnostics.service import DiagnosticExecutor
from .events import EventBroker


def create_app(
    settings: ManagerSettings | None = None,
    *,
    diagnostic_browser_adapter: BrowserAdapter | None = None,
    diagnostic_target_adapter: TargetAdapter | None = None,
    diagnostic_proxy_preflight: Callable[
        [dict[str, Any]], ProxyPreflightResult
    ]
    | None = None,
) -> FastAPI:
    resolved = settings or ManagerSettings()
    if resolved.host != "127.0.0.1":
        raise ValueError("CloakBrowser Manager must bind to 127.0.0.1")
    diagnostic_adapters = (
        diagnostic_browser_adapter,
        diagnostic_target_adapter,
        diagnostic_proxy_preflight,
    )
    if any(adapter is not None for adapter in diagnostic_adapters) and not all(
        adapter is not None for adapter in diagnostic_adapters
    ):
        raise ValueError("all diagnostic adapters must be injected together")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            summary = reconcile_runtimes(
                application.state.session_factory, application.state.settings
            )
            summary["stale_locks_removed"] = cleanup_stale_locks(
                application.state.settings
            )
            application.state.runtime_reconciliation = summary
            application.state.proxy_quality_recovered = recover_orphan_quality_runs(
                application.state.session_factory
            )
            application.state.diagnostic_recovered = (
                application.state.diagnostic_manager.recover_orphans()
            )
            if application.state.diagnostic_executor is not None:
                application.state.diagnostic_executor.start()
            yield
        finally:
            diagnostic_shutdown_error = None
            if application.state.diagnostic_executor is not None:
                try:
                    await application.state.diagnostic_executor.shutdown()
                except Exception as error:
                    diagnostic_shutdown_error = error
            application.state.runtime_manager.shutdown()
            application.state.proxy_quality_manager.shutdown()
            application.state.engine.dispose()
            if diagnostic_shutdown_error is not None:
                raise diagnostic_shutdown_error

    app = FastAPI(
        title="CloakBrowser Manager API", version="1.0.0", lifespan=lifespan
    )
    app.state.settings = resolved
    app.state.settings_store = SettingsStore(resolved.data_root / "settings.json")
    app.state.install_token = resolved.resolved_install_token()
    app.state.engine = create_engine_for(resolved)
    Base.metadata.create_all(app.state.engine)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.diagnostic_manager = DiagnosticManager(
        app.state.session_factory, data_root=resolved.data_root
    )
    app.state.event_broker = EventBroker()
    app.state.diagnostic_executor = None
    app.state.diagnostic_runner = None
    if all(adapter is not None for adapter in diagnostic_adapters):
        diagnostic_runner = DiagnosticRunner(
            app.state.session_factory,
            resolved,
            browser_adapter=diagnostic_browser_adapter,
            target_adapter=diagnostic_target_adapter,
            proxy_preflight=diagnostic_proxy_preflight,
        )
        app.state.diagnostic_runner = diagnostic_runner
        app.state.diagnostic_executor = DiagnosticExecutor(
            app.state.diagnostic_manager,
            diagnostic_runner,
            app.state.event_broker,
            cleanup_wait_seconds=resolved.diagnostic_cleanup_wait_seconds,
            shutdown_cleanup_wait_seconds=(
                resolved.diagnostic_shutdown_cleanup_wait_seconds
            ),
        )
    app.state.credential_store = KeyringCredentialStore()

    app.state.cookie_context_adapter = CookieContextAdapter(resolved)
    app.state.proxy_quick_tester = ScannerQuickTester()
    app.state.proxy_quality_manager = ProxyQualityManager(
        app.state.session_factory, app.state.credential_store, resolved
    )
    app.state.runtime_manager = RuntimeManager(
        app.state.session_factory,
        resolved,
        proxy_preflight=build_proxy_preflight(
            app.state.session_factory,
            app.state.credential_store,
            app.state.proxy_quick_tester,
        ),
    )
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

    @app.websocket("/api/v1/events")
    async def runtime_events(websocket: WebSocket) -> None:
        if websocket.headers.get("origin") != resolved.allowed_origin:
            await websocket.close(code=4403, reason="origin_rejected")
            return
        with app.state.session_factory() as session:
            try:
                validate_session(session, websocket.cookies.get(SESSION_COOKIE))
            except Exception:
                await websocket.close(code=4401, reason="authentication_required")
                return
        await websocket.accept()
        diagnostic_queue = app.state.event_broker.subscribe()
        sequence = 0
        previous = None
        try:
            while True:
                with app.state.session_factory() as session:
                    runtimes = list(
                        session.scalars(
                            select(RuntimeSession).order_by(
                                RuntimeSession.created_at.desc(), RuntimeSession.id
                            )
                        )
                    )
                    marker = tuple(
                        (item.id, item.state, item.updated_at, item.last_message)
                        for item in runtimes
                    )
                    running_session_count = count_active_runtimes(session)
                    payload = [runtime_to_dict(item) for item in runtimes]
                marker = (marker, running_session_count)
                if marker != previous:
                    sequence += 1
                    await websocket.send_json(
                        jsonable_encoder(
                            {
                                "sequence": sequence,
                                "type": "runtime.snapshot",
                                "runtimes": payload,
                                "running_session_count": running_session_count,
                            }
                        )
                    )
                    previous = marker
                try:
                    event = await asyncio.wait_for(
                        diagnostic_queue.get(), timeout=0.05
                    )
                except asyncio.TimeoutError:
                    continue
                sequence += 1
                await websocket.send_json(
                    jsonable_encoder({"sequence": sequence, **event})
                )
        except WebSocketDisconnect:
            return
        finally:
            app.state.event_broker.unsubscribe(diagnostic_queue)

    return app
