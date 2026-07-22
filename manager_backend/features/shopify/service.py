"""Stores, AI settings, catalogs, themes, CSV inspection, capability mapping.

Secrets (OAuth client id/secret, access token, OpenAI key) go to the secure
CredentialStore keyed by a ref; the DB holds only refs + non-secret metadata,
and API payloads carry `connected`/`has_api_key` flags, never the secrets.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...errors import ManagerError
from ...models import ShopifyAiSetting, ShopifyStore
from ..proxies.credentials import CredentialStore, ProxyCredential
from ..proxies.service import resolve_proxy_url
from .clients import ShopifyClient, StoreContext


CAPABILITY_KEYS = (
    "write_products",
    "write_pages",
    "write_legal_policies",
    "write_navigation",
    "write_themes",
)

# Built-in product catalogs. ponytail: a small seed set; the CSV path covers
# anything else, and Quantum's larger catalogs can be added as data later.
CATALOGS = [
    {
        "id": "cat_home",
        "name": "Home & Living Essentials",
        "niche": "Home & Living",
        "products": [
            {"handle": "linen-throw", "title": "Linen Throw Blanket", "price": "49.00"},
            {"handle": "ceramic-vase", "title": "Ceramic Table Vase", "price": "28.00"},
            {"handle": "oak-tray", "title": "Oak Serving Tray", "price": "36.00"},
        ],
    },
    {
        "id": "cat_fitness",
        "name": "Active & Fitness",
        "niche": "Fitness",
        "products": [
            {"handle": "resistance-band", "title": "Resistance Band Set", "price": "24.00"},
            {"handle": "yoga-mat", "title": "Grip Yoga Mat", "price": "39.00"},
        ],
    },
]

_PRODUCT_COLUMN_ALIASES = {
    "handle": {"handle", "url_handle", "slug"},
    "title": {"title", "name", "product_title", "product name"},
    "price": {"price", "variant price", "amount"},
    "type": {"type", "product_type", "category"},
    "vendor": {"vendor", "brand"},
    "tags": {"tags"},
    "image": {"image", "image src", "image_url"},
}

_INTEGRATED_THEMES = [
    {"id": "integrated:aurora", "name": "Aurora (CloakBrowser)", "role": "demo", "presets": ["Minimal", "Bold"]},
]


# --- capability map ----------------------------------------------------------
def capabilities_from_scopes(scopes: list[str]) -> dict:
    granted = set(scopes)
    content = "write_content" in granted
    return {
        "write_products": "write_products" in granted,
        "write_pages": content or "write_pages" in granted,
        "write_legal_policies": content or "write_legal_policies" in granted,
        "write_navigation": "write_navigation" in granted,
        "write_themes": "write_themes" in granted,
    }


# --- serialization -----------------------------------------------------------
def store_to_dict(store: ShopifyStore) -> dict:
    info = dict(store.shop_info_json or {})
    return {
        "id": store.id,
        "label": store.label,
        "shop_domain": store.shop_domain,
        "connected": store.token_ref is not None,
        "scopes": list(store.scopes_json or []),
        "capabilities": dict(store.inspection_json or {}),
        "shop_name": info.get("shop_name") or store.store_name or None,
        "product_count": info.get("product_count"),
        "proxy_id": store.proxy_id,
        "exit_ip": info.get("exit_ip"),
        "niche": store.niche,
        "language": store.language,
        "created_at": store.created_at,
        "updated_at": store.updated_at,
    }


def _normalize_domain(raw: str) -> str:
    domain = raw.strip().lower().replace("https://", "").replace("http://", "").strip("/")
    if not domain:
        raise ManagerError("invalid_store", "A shop domain is required.", 422)
    return domain


def _get_store(session: Session, store_id: str) -> ShopifyStore:
    store = session.get(ShopifyStore, store_id)
    if store is None:
        raise ManagerError("store_not_found", "The requested store was not found.", 404)
    return store


# --- token / context ---------------------------------------------------------
def _ensure_token(cred_store: CredentialStore, store: ShopifyStore, client: ShopifyClient) -> str:
    now = datetime.now(timezone.utc)
    if store.token_ref and (store.token_expires_at is None or store.token_expires_at > now):
        cached = cred_store.get(store.token_ref)
        if cached:
            return cached.password
    creds = cred_store.get(store.credentials_ref)
    if creds is None:
        raise ManagerError("store_credentials_missing", "Reconnect the store.", 422)
    token, scopes, expires = client.exchange_token(store.shop_domain, creds.username, creds.password)
    if store.token_ref is None:
        store.token_ref = str(uuid4())
    cred_store.put(store.token_ref, ProxyCredential("token", token))
    store.token_expires_at = expires
    store.scopes_json = scopes
    store.inspection_json = capabilities_from_scopes(scopes)
    return token


def store_context(
    session: Session, cred_store: CredentialStore, store: ShopifyStore, client: ShopifyClient
) -> StoreContext:
    token = _ensure_token(cred_store, store, client)
    proxy_url = None
    if store.proxy_id:
        try:
            proxy_url = resolve_proxy_url(session, cred_store, store.proxy_id)
        except ManagerError:
            proxy_url = None
    return StoreContext(domain=store.shop_domain, token=token, proxy_url=proxy_url)


# --- stores ------------------------------------------------------------------
def list_stores(session: Session) -> list[dict]:
    stores = session.scalars(
        select(ShopifyStore).order_by(ShopifyStore.created_at.desc())
    ).all()
    return [store_to_dict(store) for store in stores]


def get_store(session: Session, store_id: str) -> dict:
    return store_to_dict(_get_store(session, store_id))


def connect_store(
    session: Session, cred_store: CredentialStore, client: ShopifyClient, payload
) -> dict:
    domain = _normalize_domain(payload.shop_domain)
    token, scopes, expires = client.exchange_token(domain, payload.client_id, payload.client_secret)

    credentials_ref = str(uuid4())
    cred_store.put(credentials_ref, ProxyCredential(payload.client_id, payload.client_secret))
    token_ref = str(uuid4())
    cred_store.put(token_ref, ProxyCredential("token", token))

    store = ShopifyStore(
        label=(payload.label.strip() or domain),
        shop_domain=domain,
        scopes_json=scopes,
        shop_info_json={},
        inspection_json=capabilities_from_scopes(scopes),
        proxy_id=payload.proxy_id,
        credentials_ref=credentials_ref,
        token_ref=token_ref,
        token_expires_at=expires,
        store_name=domain.split(".")[0],
        support_email=f"support@{domain}",
    )
    try:
        info = client.shop_info(StoreContext(domain=domain, token=token, proxy_url=None))
        store.shop_info_json = info
        if info.get("shop_name"):
            store.store_name = info["shop_name"]
    except ManagerError:
        pass  # a shop-info blip must not fail an otherwise-valid connection

    session.add(store)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        cred_store.delete(credentials_ref)
        cred_store.delete(token_ref)
        raise ManagerError("store_already_connected", "This store is already connected.", 409) from None
    session.refresh(store)
    return store_to_dict(store)


def inspect_store(
    session: Session, cred_store: CredentialStore, client: ShopifyClient, store_id: str
) -> dict:
    store = _get_store(session, store_id)
    ctx = store_context(session, cred_store, store, client)
    try:
        store.shop_info_json = {**dict(store.shop_info_json or {}), **client.shop_info(ctx)}
    except ManagerError:
        pass
    # ponytail: lean analysis — default niche/English. Keyword niche scoring is a
    # later data addition; a manual override always wins downstream.
    if not store.language:
        store.language = "en"
    if not store.niche:
        store.niche = "General store"
    session.commit()
    session.refresh(store)
    return store_to_dict(store)


def set_network_route(session: Session, store_id: str, proxy_id: str | None) -> dict:
    store = _get_store(session, store_id)
    store.proxy_id = proxy_id
    session.commit()
    session.refresh(store)
    return store_to_dict(store)


def delete_store(session: Session, cred_store: CredentialStore, store_id: str) -> None:
    store = _get_store(session, store_id)
    for ref in (store.credentials_ref, store.token_ref):
        if ref:
            cred_store.delete(ref)
    session.delete(store)
    session.commit()


def get_profile(session: Session, store_id: str) -> dict:
    store = _get_store(session, store_id)
    return {
        "niche": store.niche,
        "language": store.language,
        "store_name": store.store_name,
        "support_email": store.support_email,
    }


def update_profile(session: Session, store_id: str, payload) -> dict:
    store = _get_store(session, store_id)
    store.niche = payload.niche
    store.language = payload.language
    store.store_name = payload.store_name
    store.support_email = payload.support_email
    session.commit()
    return get_profile(session, store_id)


# --- AI settings -------------------------------------------------------------
def get_ai_settings(session: Session) -> dict:
    row = session.get(ShopifyAiSetting, 1)
    if row is None:
        return {"enabled": False, "provider": "openai", "model": "gpt-image-1", "has_api_key": False}
    return {
        "enabled": row.enabled,
        "provider": row.provider,
        "model": row.model,
        "has_api_key": row.api_key_ref is not None,
    }


def update_ai_settings(session: Session, cred_store: CredentialStore, payload) -> dict:
    row = session.get(ShopifyAiSetting, 1)
    if row is None:
        row = ShopifyAiSetting(id=1)
        session.add(row)
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.provider is not None:
        row.provider = payload.provider
    if payload.model is not None:
        row.model = payload.model
    if payload.api_key:
        ref = str(uuid4())
        cred_store.put(ref, ProxyCredential(row.provider, payload.api_key))
        row.api_key_ref = ref
    session.commit()
    return get_ai_settings(session)


# --- catalogs / themes / CSV -------------------------------------------------
def list_catalogs() -> list[dict]:
    return [
        {
            "id": catalog["id"],
            "name": catalog["name"],
            "niche": catalog["niche"],
            "product_count": len(catalog["products"]),
        }
        for catalog in CATALOGS
    ]


def theme_library(
    session: Session, cred_store: CredentialStore, client: ShopifyClient, store_id: str
) -> dict:
    store = _get_store(session, store_id)
    ctx = store_context(session, cred_store, store, client)
    try:
        remote = client.list_themes(ctx)
    except ManagerError:
        remote = []
    session.commit()  # persist any token refresh from store_context
    return {"integrated": list(_INTEGRATED_THEMES), "store": remote}


def _map_columns(headers: list[str]) -> tuple[dict, list[str]]:
    lowered = {header.strip().lower(): header for header in headers}
    mapping: dict[str, str] = {}
    for field, aliases in _PRODUCT_COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                mapping[field] = lowered[alias]
                break
    unmapped = [header for header in headers if header not in mapping.values()]
    return mapping, unmapped


def inspect_product_csv(content: str) -> dict:
    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames or []
    mapping, unmapped = _map_columns(list(headers))
    rows = list(reader)
    sample = []
    for row in rows[:5]:
        sample.append(
            {
                "handle": str(row.get(mapping.get("handle", ""), "") or "").strip(),
                "title": str(row.get(mapping.get("title", ""), "") or "").strip(),
                "price": str(row.get(mapping.get("price", ""), "") or "").strip(),
                "variants": 1,
            }
        )
    return {
        "total": len(rows),
        "sample": sample,
        "columns_mapped": sorted(mapping.keys()),
        "columns_unmapped": unmapped,
    }
