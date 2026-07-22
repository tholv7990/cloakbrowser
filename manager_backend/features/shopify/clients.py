"""The seam between the Shopify Builder orchestration and external HTTP.

ShopifyClient wraps the Shopify Admin GraphQL API + OAuth; OpenAIImageClient
wraps image generation. The default implementations make real HTTP calls (routed
through a store's proxy for a consistent exit IP) but are exercised only in
production — tests inject fakes, and the orchestration (capability map, plan
staging, the idempotent pipeline, theme-file bisection, secret handling) is what
gets verified.

Draft-only by construction: there is no publish method anywhere in this
interface, so the pipeline structurally cannot flip a theme to PUBLISHED.

ponytail: the real client is a lean, best-effort port of Quantum's GraphQL
bodies; it is not verified against a live store here (no test hits Shopify).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from ...errors import ManagerError


SHOPIFY_API_VERSION = "2026-07"


@dataclass(frozen=True)
class StoreContext:
    domain: str
    token: str
    proxy_url: str | None = None


class ShopifyClient(Protocol):
    def exchange_token(
        self, domain: str, client_id: str, client_secret: str
    ) -> tuple[str, list[str], datetime | None]: ...

    def shop_info(self, ctx: StoreContext) -> dict: ...

    def list_themes(self, ctx: StoreContext) -> list[dict]: ...

    def upsert_products(self, ctx: StoreContext, products: list[dict]) -> dict: ...

    def upsert_pages(self, ctx: StoreContext, pages: list[dict]) -> dict: ...

    def update_policies(self, ctx: StoreContext, policies: list[dict]) -> dict: ...

    def upsert_menus(self, ctx: StoreContext, menus: list[dict]) -> dict: ...

    def duplicate_theme(self, ctx: StoreContext, source_theme_id: str, name: str) -> str: ...

    def upsert_theme_file_batch(
        self, ctx: StoreContext, theme_id: str, files: list[dict]
    ) -> list[str]:
        """Upsert a batch of theme files; return the keys Shopify rejected."""

    def theme_urls(self, ctx: StoreContext, theme_id: str) -> tuple[str, str]: ...


class OpenAIImageClient(Protocol):
    def generate(self, api_key: str, *, prompt: str, model: str) -> bytes: ...


def _require_httpx():
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - httpx ships with fastapi
        raise ManagerError(
            "shopify_http_unavailable", "The HTTP client is unavailable.", 500
        ) from exc
    return httpx


class HttpShopifyClient:
    def __init__(self, api_version: str = SHOPIFY_API_VERSION):
        self._api_version = api_version

    def _client(self, proxy_url: str | None):
        httpx = _require_httpx()
        return httpx.Client(timeout=30.0, proxy=proxy_url)

    def exchange_token(self, domain, client_id, client_secret):
        with self._client(None) as client:
            response = client.post(
                f"https://{domain}/admin/oauth/access_token",
                json={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "client_credentials",
                },
            )
        if response.status_code >= 400:
            raise ManagerError(
                "shopify_auth_failed",
                "Shopify rejected the store credentials.",
                422,
            )
        body = response.json()
        token = str(body.get("access_token") or "")
        if not token:
            raise ManagerError("shopify_auth_failed", "Shopify returned no access token.", 422)
        scope_raw = str(body.get("scope") or "")
        scopes = [s.strip() for s in scope_raw.replace(",", " ").split() if s.strip()]
        expires_at = None
        if body.get("expires_in"):
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(body["expires_in"]))
        return token, scopes, expires_at

    def _graphql(self, ctx: StoreContext, query: str, variables: dict | None = None) -> dict:
        with self._client(ctx.proxy_url) as client:
            response = client.post(
                f"https://{ctx.domain}/admin/api/{self._api_version}/graphql.json",
                headers={"X-Shopify-Access-Token": ctx.token},
                json={"query": query, "variables": variables or {}},
            )
        if response.status_code >= 400:
            raise ManagerError(
                "shopify_api_error", f"Shopify API returned HTTP {response.status_code}.", 502
            )
        payload = response.json()
        if payload.get("errors"):
            raise ManagerError("shopify_api_error", "Shopify GraphQL query failed.", 502)
        return payload.get("data") or {}

    def shop_info(self, ctx):
        data = self._graphql(ctx, "{ shop { name } productsCount { count } }")
        return {
            "shop_name": (data.get("shop") or {}).get("name"),
            "product_count": (data.get("productsCount") or {}).get("count"),
        }

    def list_themes(self, ctx):
        data = self._graphql(
            ctx, "{ themes(first: 50) { nodes { id name role } } }"
        )
        nodes = ((data.get("themes") or {}).get("nodes")) or []
        return [
            {
                "id": node.get("id"),
                "name": node.get("name"),
                "role": str(node.get("role") or "").lower(),
                "presets": [],
            }
            for node in nodes
        ]

    # The mutation wrappers return {"userErrors": [...]}; the pipeline turns a
    # non-empty userErrors into a step failure without raising.
    def upsert_products(self, ctx, products):
        errors: list[str] = []
        for product in products:
            data = self._graphql(
                ctx,
                "mutation productSet($input: ProductSetInput!) {"
                " productSet(input: $input, synchronous: true) { userErrors { message } } }",
                {"input": product},
            )
            errors += [e["message"] for e in ((data.get("productSet") or {}).get("userErrors") or [])]
        return {"count": len(products), "userErrors": errors}

    def upsert_pages(self, ctx, pages):
        errors: list[str] = []
        for page in pages:
            data = self._graphql(
                ctx,
                "mutation pageCreate($page: PageCreateInput!) {"
                " pageCreate(page: $page) { userErrors { message } } }",
                {"page": page},
            )
            errors += [e["message"] for e in ((data.get("pageCreate") or {}).get("userErrors") or [])]
        return {"count": len(pages), "userErrors": errors}

    def update_policies(self, ctx, policies):
        errors: list[str] = []
        for policy in policies:
            data = self._graphql(
                ctx,
                "mutation shopPolicyUpdate($shopPolicy: ShopPolicyInput!) {"
                " shopPolicyUpdate(shopPolicy: $shopPolicy) { userErrors { message } } }",
                {"shopPolicy": policy},
            )
            errors += [e["message"] for e in ((data.get("shopPolicyUpdate") or {}).get("userErrors") or [])]
        return {"count": len(policies), "userErrors": errors}

    def upsert_menus(self, ctx, menus):
        errors: list[str] = []
        for menu in menus:
            data = self._graphql(
                ctx,
                "mutation menuCreate($title: String!, $handle: String!, $items: [MenuItemCreateInput!]!) {"
                " menuCreate(title: $title, handle: $handle, items: $items) { userErrors { message } } }",
                menu,
            )
            errors += [e["message"] for e in ((data.get("menuCreate") or {}).get("userErrors") or [])]
        return {"count": len(menus), "userErrors": errors}

    def duplicate_theme(self, ctx, source_theme_id, name):
        data = self._graphql(
            ctx,
            "mutation themeDuplicate($id: ID!, $name: String) {"
            " themeDuplicate(id: $id, name: $name) { theme { id } userErrors { message } } }",
            {"id": source_theme_id, "name": name},
        )
        result = data.get("themeDuplicate") or {}
        theme = result.get("theme") or {}
        if not theme.get("id"):
            raise ManagerError("shopify_theme_error", "Shopify did not return a duplicated theme.", 502)
        return theme["id"]  # role stays UNPUBLISHED — never published

    def upsert_theme_file_batch(self, ctx, theme_id, files):
        data = self._graphql(
            ctx,
            "mutation themeFilesUpsert($themeId: ID!, $files: [OnlineStoreThemeFilesUpsertFileInput!]!) {"
            " themeFilesUpsert(themeId: $themeId, files: $files) {"
            " upsertedThemeFiles { filename } userErrors { filename message } } }",
            {"themeId": theme_id, "files": files},
        )
        result = data.get("themeFilesUpsert") or {}
        rejected = {e.get("filename") for e in (result.get("userErrors") or []) if e.get("filename")}
        return [f["key"] for f in files if f.get("key") in rejected]

    def theme_urls(self, ctx, theme_id):
        numeric = str(theme_id).rsplit("/", 1)[-1]
        admin = f"https://{ctx.domain}/admin/themes/{numeric}/editor"
        preview = f"https://{ctx.domain}/?preview_theme_id={numeric}"
        return admin, preview


class HttpOpenAIImageClient:
    def generate(self, api_key, *, prompt, model):
        import base64

        httpx = _require_httpx()
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "prompt": prompt, "size": "1536x1024", "n": 1},
            )
        if response.status_code >= 400:
            raise ManagerError("openai_error", "Image generation failed.", 502)
        data = response.json().get("data") or [{}]
        return base64.b64decode(data[0].get("b64_json") or "")
