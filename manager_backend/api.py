from fastapi import APIRouter, Depends

from .features.catalog.routes import router as catalog_router
from .features.profiles.routes import router as profiles_router
from .dependencies import require_authenticated_session


api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated_session)])
api_router.include_router(catalog_router)
api_router.include_router(profiles_router)
