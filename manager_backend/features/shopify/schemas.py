from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from ...schemas.common import StrictModel


class StoreCapabilities(StrictModel):
    write_products: bool = False
    write_pages: bool = False
    write_legal_policies: bool = False
    write_navigation: bool = False
    write_themes: bool = False


class ShopifyStoreRead(StrictModel):
    id: str
    label: str
    shop_domain: str
    connected: bool
    scopes: list[str]
    capabilities: StoreCapabilities
    shop_name: str | None
    product_count: int | None
    proxy_id: str | None
    exit_ip: str | None
    niche: str | None
    language: str | None
    created_at: datetime
    updated_at: datetime


class ConnectStorePayload(StrictModel):
    label: str = Field(default="", max_length=160)
    shop_domain: str = Field(min_length=1, max_length=255)
    client_id: str = Field(min_length=1, max_length=200, json_schema_extra={"writeOnly": True})
    client_secret: str = Field(min_length=1, max_length=500, json_schema_extra={"writeOnly": True})
    proxy_id: str | None = None


class NetworkRoutePayload(StrictModel):
    proxy_id: str | None = None


class StoreProfileRead(StrictModel):
    niche: str | None
    language: str | None
    store_name: str
    support_email: str


class StoreProfileWrite(StrictModel):
    niche: str | None = None
    language: str | None = None
    store_name: str = Field(default="", max_length=160)
    support_email: str = Field(default="", max_length=200)


class AiImageSettingsRead(StrictModel):
    enabled: bool
    provider: str
    model: str
    has_api_key: bool


class AiImageSettingsWrite(StrictModel):
    enabled: bool | None = None
    provider: str | None = Field(default=None, max_length=40)
    model: str | None = Field(default=None, max_length=80)
    api_key: str | None = Field(default=None, max_length=500, json_schema_extra={"writeOnly": True})


class ThemeInfo(StrictModel):
    id: str
    name: str
    role: Literal["main", "unpublished", "demo"]
    presets: list[str]


class ThemeLibrary(StrictModel):
    integrated: list[ThemeInfo]
    store: list[ThemeInfo]


class ProductRow(StrictModel):
    handle: str
    title: str
    price: str
    variants: int


class ProductCsvInspection(StrictModel):
    total: int
    sample: list[ProductRow]
    columns_mapped: list[str]
    columns_unmapped: list[str]


class ProductCsvInspectRequest(StrictModel):
    content: str = Field(min_length=1, max_length=5_000_000, json_schema_extra={"writeOnly": True})


class ProductCatalog(StrictModel):
    id: str
    name: str
    niche: str
    product_count: int


class PlanStepRead(StrictModel):
    key: str
    status: Literal["planned", "ready", "blocked", "running", "completed", "failed"]
    reason: str | None
    error: str | None


class BuildPlanRead(StrictModel):
    id: str
    store_id: str
    status: Literal["staged", "running", "completed", "partial", "failed"]
    mode: Literal["draft_only"]
    niche: str
    language: str
    theme_name: str
    preset: str
    product_count: int
    ai_hero: bool
    steps: list[PlanStepRead]
    admin_url: str | None
    preview_url: str | None
    created_at: datetime


class CreatePlanPayload(StrictModel):
    theme_id: str = Field(min_length=1)
    preset: str = Field(default="", max_length=80)
    product_source: Literal["catalog", "csv"]
    catalog_id: str | None = None
    niche_override: str | None = None
    ai_hero: bool = False


class ExecutePlanPayload(StrictModel):
    confirm: bool = False
