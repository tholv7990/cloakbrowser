from fastapi import APIRouter, Depends

from .features.catalog.routes import router as catalog_router
from .security import require_local_token


api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_local_token)])
api_router.include_router(catalog_router)
