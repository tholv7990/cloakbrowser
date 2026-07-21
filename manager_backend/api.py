from fastapi import APIRouter, Depends

from .features.catalog.routes import router as catalog_router
from .features.app.routes import router as app_router
from .features.profiles.routes import router as profiles_router
from .features.runtime.routes import router as runtime_router
from .features.proxies.routes import router as proxies_router
from .features.settings.routes import router as settings_router
from .dependencies import require_authenticated_session
from .schemas.common import ErrorEnvelope


api_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_authenticated_session)],
    responses={
        401: {"model": ErrorEnvelope, "description": "Authentication required"},
        403: {"model": ErrorEnvelope, "description": "Origin or CSRF rejected"},
        422: {"model": ErrorEnvelope, "description": "Request validation failed"},
    },
)
api_router.include_router(app_router)
api_router.include_router(catalog_router)
api_router.include_router(profiles_router)
api_router.include_router(runtime_router)
api_router.include_router(proxies_router)
api_router.include_router(settings_router)
