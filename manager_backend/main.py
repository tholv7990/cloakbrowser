from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .auth.routes import router as auth_router
from .config import ManagerSettings
from .db import apply_schema, create_engine_for, create_session_factory
from .errors import install_error_handlers
from .maintenance import MaintenanceGate
from .dependencies import require_authenticated_session
from .features.runtime.manager import RuntimeManager
from .features.license.service import make_license_gate
from .features.account.service import AccountService
from .features.account.secrets import KeyringSecretStore
from .features.account.refresher import start_entitlement_refresher
from .features.runtime.reconcile import cleanup_stale_locks, reconcile_runtimes
from .features.runtime.routes import runtime_to_dict
from .features.runtime.snapshots import RuntimeSnapshotCache
from .features.runtime.input_sync import InputSyncService
from .features.runtime.windows import WINDOW_MANAGER
from .auth.sessions import validate_session
from .dependencies import SESSION_COOKIE
from .features.proxies.credentials import KeyringCredentialStore
from .features.proxies.testing import ScannerQuickTester
from .features.proxies.providers import DefaultProviderClient
from .features.proxies.service import build_proxy_health, build_proxy_preflight
from .features.proxies.quality import ProxyQualityManager, recover_orphan_quality_runs
from .features.backups.service import maybe_auto_backup
from .features.automation.controller import StubAutomationController
from .features.automation.coordinator import RunCoordinator, recover_interrupted_runs
from .features.shopify.clients import HttpOpenAIImageClient, HttpShopifyClient
from .features.shopify.pipeline import recover_interrupted_plans
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
            application.state.automation_recovered = recover_interrupted_runs(
                application.state.session_factory
            )
            application.state.shopify_plans_recovered = recover_interrupted_plans(
                application.state.session_factory
            )
            application.state.diagnostic_recovered = (
                application.state.diagnostic_manager.recover_orphans()
            )
            if application.state.diagnostic_executor is not None:
                application.state.diagnostic_executor.start()
            if application.state.settings.auto_backup_enabled:
                try:
                    application.state.auto_backup = maybe_auto_backup(
                        application.state.engine, application.state.settings.data_root
                    )
                except Exception:  # a backup failure must never block startup
                    application.state.auto_backup = None
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
            # Await workers before disposing the engine — a worker still holding a
            # DB session must not have the engine pulled out from under it.
            runs_clean = application.state.automation_runs.shutdown()
            if not runs_clean:
                logging.getLogger("manager").warning(
                    "automation run workers did not all finish before engine dispose"
                )
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
    apply_schema(app.state.engine, resolved.data_root)
    app.state.session_factory = create_session_factory(app.state.engine)
    # Serializes a destructive backup-restore against every worker-spawning /
    # state-changing endpoint (they take a gate operation; restore takes it
    # exclusively).
    app.state.maintenance_gate = MaintenanceGate()
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
    app.state.proxy_provider_client = DefaultProviderClient()
    app.state.automation_controller = StubAutomationController()
    app.state.automation_runs = RunCoordinator(
        app.state.session_factory,
        app.state.credential_store,
        app.state.automation_controller,
    )
    app.state.shopify_client = HttpShopifyClient()
    app.state.openai_image_client = HttpOpenAIImageClient()
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
        proxy_health=build_proxy_health(app.state.proxy_quick_tester),
        license_gate=make_license_gate(resolved),
    )
    app.state.window_manager = WINDOW_MANAGER
    app.state.input_sync = InputSyncService()
    app.state.account_service = AccountService(
        resolved, secret_store=KeyringSecretStore()
    )
    # Keep the entitlement fresh in the background (no-op until signed in + configured).
    if resolved.cloud_base_url:
        start_entitlement_refresher(
            lambda: app.state.account_service,
            interval_seconds=resolved.entitlement_refresh_interval_seconds,
        )
    app.state.login_failures = {}
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved.allowed_origin],
        allow_credentials=True,
        allow_methods=["*"] ,
        # Authorization: the desktop webview sends the per-install Bearer token on
        # every request (cross-origin from http://tauri.localhost), which makes even a
        # GET preflighted — omit it and the browser blocks every call ("cannot reach").
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    )
    install_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(api_router)

    @app.get("/livez")
    async def livez() -> dict[str, str]:
        # Public, unauthenticated liveness probe — the desktop shell polls this to
        # gate the UI on the sidecar being up. Leaks nothing (no auth, no state).
        return {"status": "ok"}

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
        snapshot_cache = RuntimeSnapshotCache()
        sequence = 0
        try:
            while True:
                with app.state.session_factory() as session:
                    snapshot = snapshot_cache.poll(session)
                    payload = (
                        [runtime_to_dict(item) for item in snapshot.runtimes]
                        if snapshot.changed
                        else []
                    )
                if snapshot.changed:
                    sequence += 1
                    await websocket.send_json(
                        jsonable_encoder(
                            {
                                "sequence": sequence,
                                "type": "runtime.snapshot",
                                "runtimes": payload,
                                "running_session_count": snapshot.running_count,
                            }
                        )
                    )
                try:
                    event = await asyncio.wait_for(
                        diagnostic_queue.get(), timeout=0.25
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
