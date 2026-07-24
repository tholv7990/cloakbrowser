from fastapi import APIRouter, Depends

from .features.catalog.routes import router as catalog_router
from .features.app.routes import router as app_router
from .features.profiles.routes import router as profiles_router
from .features.portability.routes import router as portability_router
from .features.runtime.routes import router as runtime_router
from .features.proxies.provider_routes import router as proxy_providers_router
from .features.proxies.routes import router as proxies_router
from .features.settings.routes import router as settings_router
from .features.extensions.routes import router as extensions_router
from .features.diagnostics.routes import router as diagnostics_router
from .features.resources.routes import router as resources_router
from .features.backups.routes import router as backups_router
from .features.media.routes import router as media_router
from .features.automation.routes import router as automation_router
from .features.shopify.routes import router as shopify_router
from .features.license.routes import router as license_router
from .features.account.routes import router as account_router
from .dependencies import require_authenticated_session
from .security import require_local_token
from .schemas.common import ErrorEnvelope


api_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_authenticated_session), Depends(require_local_token)],
    responses={
        401: {"model": ErrorEnvelope, "description": "Authentication required"},
        403: {"model": ErrorEnvelope, "description": "Origin or CSRF rejected"},
        422: {"model": ErrorEnvelope, "description": "Request validation failed"},
    },
)
api_router.include_router(app_router)
api_router.include_router(catalog_router)
api_router.include_router(profiles_router)
api_router.include_router(portability_router)
api_router.include_router(runtime_router)
api_router.include_router(proxy_providers_router)  # before proxies_router: /proxies/providers
api_router.include_router(proxies_router)
api_router.include_router(settings_router)
api_router.include_router(extensions_router)
api_router.include_router(diagnostics_router)
api_router.include_router(resources_router)
api_router.include_router(backups_router)
api_router.include_router(media_router)
api_router.include_router(automation_router)
api_router.include_router(shopify_router)
api_router.include_router(license_router)
api_router.include_router(account_router)
