from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from ...dependencies import get_session
from . import pipeline, service
from .schemas import (
    AiImageSettingsRead,
    AiImageSettingsWrite,
    BuildPlanRead,
    ConnectStorePayload,
    CreatePlanPayload,
    ExecutePlanPayload,
    NetworkRoutePayload,
    ProductCatalog,
    ProductCsvInspectRequest,
    ProductCsvInspection,
    ShopifyStoreRead,
    StoreProfileRead,
    StoreProfileWrite,
    ThemeLibrary,
)


router = APIRouter(prefix="/shopify-builder", tags=["shopify"])
SessionDependency = Annotated[Session, Depends(get_session)]
_CREATED = status.HTTP_201_CREATED
_NO_CONTENT = status.HTTP_204_NO_CONTENT


# --- stores -----------------------------------------------------------------
@router.get("/stores", response_model=list[ShopifyStoreRead], operation_id="shopify_stores_list")
def list_stores(session: SessionDependency):
    return service.list_stores(session)


@router.post("/stores/connect", response_model=ShopifyStoreRead, status_code=_CREATED, operation_id="shopify_stores_connect")
def connect_store(payload: ConnectStorePayload, request: Request, session: SessionDependency):
    return service.connect_store(
        session, request.app.state.credential_store, request.app.state.shopify_client, payload
    )


@router.post("/stores/{store_id}/inspect", response_model=ShopifyStoreRead, operation_id="shopify_stores_inspect")
def inspect_store(store_id: str, request: Request, session: SessionDependency):
    return service.inspect_store(
        session, request.app.state.credential_store, request.app.state.shopify_client, store_id
    )


@router.put("/stores/{store_id}/network-route", response_model=ShopifyStoreRead, operation_id="shopify_stores_network_route")
def set_network_route(store_id: str, payload: NetworkRoutePayload, session: SessionDependency):
    return service.set_network_route(session, store_id, payload.proxy_id)


@router.delete("/stores/{store_id}", status_code=_NO_CONTENT, operation_id="shopify_stores_delete")
def delete_store(store_id: str, request: Request, session: SessionDependency) -> Response:
    service.delete_store(session, request.app.state.credential_store, store_id)
    return Response(status_code=_NO_CONTENT)


@router.get("/stores/{store_id}/profile", response_model=StoreProfileRead, operation_id="shopify_store_profile_get")
def get_store_profile(store_id: str, session: SessionDependency):
    return service.get_profile(session, store_id)


@router.put("/stores/{store_id}/profile", response_model=StoreProfileRead, operation_id="shopify_store_profile_update")
def update_store_profile(store_id: str, payload: StoreProfileWrite, session: SessionDependency):
    return service.update_profile(session, store_id, payload)


# --- AI images --------------------------------------------------------------
@router.get("/ai-images/settings", response_model=AiImageSettingsRead, operation_id="shopify_ai_settings_get")
def get_ai_settings(session: SessionDependency):
    return service.get_ai_settings(session)


@router.put("/ai-images/settings", response_model=AiImageSettingsRead, operation_id="shopify_ai_settings_update")
def update_ai_settings(payload: AiImageSettingsWrite, request: Request, session: SessionDependency):
    return service.update_ai_settings(session, request.app.state.credential_store, payload)


# --- themes / catalogs / products -------------------------------------------
@router.get("/stores/{store_id}/themes/library", response_model=ThemeLibrary, operation_id="shopify_themes_library")
def themes_library(store_id: str, request: Request, session: SessionDependency):
    return service.theme_library(
        session, request.app.state.credential_store, request.app.state.shopify_client, store_id
    )


@router.get("/catalogs", response_model=list[ProductCatalog], operation_id="shopify_catalogs_list")
def list_catalogs():
    return service.list_catalogs()


@router.post("/stores/{store_id}/product-csv/inspect", response_model=ProductCsvInspection, operation_id="shopify_product_csv_inspect")
def inspect_product_csv(store_id: str, payload: ProductCsvInspectRequest, session: SessionDependency):
    service.get_store(session, store_id)  # 404 if the store is gone
    return service.inspect_product_csv(payload.content)


# --- plans ------------------------------------------------------------------
@router.post("/stores/{store_id}/plans", response_model=BuildPlanRead, status_code=_CREATED, operation_id="shopify_plans_create")
def create_plan(store_id: str, payload: CreatePlanPayload, session: SessionDependency):
    return pipeline.create_build_plan(session, store_id, payload)


@router.get("/stores/{store_id}/plans/{plan_id}", response_model=BuildPlanRead, operation_id="shopify_plans_get")
def get_plan(store_id: str, plan_id: str, session: SessionDependency):
    return pipeline.get_plan(session, store_id, plan_id)


@router.post("/stores/{store_id}/plans/{plan_id}/execute", response_model=BuildPlanRead, operation_id="shopify_plans_execute")
def execute_plan(store_id: str, plan_id: str, payload: ExecutePlanPayload, request: Request, session: SessionDependency):
    return pipeline.execute_build_plan(
        session,
        request.app.state.credential_store,
        request.app.state.shopify_client,
        request.app.state.openai_image_client,
        store_id,
        plan_id,
        payload.confirm,
    )
