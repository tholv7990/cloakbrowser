from __future__ import annotations

from manager_backend.features.proxies.credentials import MemoryCredentialStore
from manager_backend.models import ShopifyStore


_MUTATIONS = {
    "upsert_products",
    "upsert_pages",
    "update_policies",
    "upsert_menus",
    "duplicate_theme",
    "upsert_theme_file_batch",
}
_FULL_SCOPES = [
    "read_products", "write_products", "write_content", "write_navigation", "write_themes",
]

_BASE = "/api/v1/shopify-builder"


class FakeShopify:
    def __init__(self):
        self.calls: list[tuple] = []
        self.scopes = list(_FULL_SCOPES)
        self.page_errors: list[str] = []
        self.reject_file: str | None = None

    def exchange_token(self, domain, client_id, client_secret):
        self.calls.append(("exchange_token", domain))
        return f"tok-{domain}", list(self.scopes), None

    def shop_info(self, ctx):
        self.calls.append(("shop_info", ctx.domain))
        return {"shop_name": "Test Shop", "product_count": 7}

    def list_themes(self, ctx):
        return [{"id": "gid://shopify/Theme/1", "name": "Main", "role": "main", "presets": []}]

    def upsert_products(self, ctx, products):
        self.calls.append(("upsert_products", len(products)))
        return {"count": len(products), "userErrors": []}

    def upsert_pages(self, ctx, pages):
        self.calls.append(("upsert_pages", len(pages)))
        return {"count": len(pages), "userErrors": list(self.page_errors)}

    def update_policies(self, ctx, policies):
        self.calls.append(("update_policies", len(policies)))
        return {"count": len(policies), "userErrors": []}

    def upsert_menus(self, ctx, menus):
        self.calls.append(("upsert_menus", len(menus)))
        return {"count": len(menus), "userErrors": []}

    def duplicate_theme(self, ctx, source_theme_id, name):
        self.calls.append(("duplicate_theme", source_theme_id, name))
        return "gid://shopify/Theme/99"

    def upsert_theme_file_batch(self, ctx, theme_id, files):
        keys = [f["key"] for f in files]
        self.calls.append(("upsert_theme_file_batch", keys))
        if self.reject_file and self.reject_file in keys:
            return list(keys)
        return []

    def theme_urls(self, ctx, theme_id):
        numeric = theme_id.rsplit("/", 1)[-1]
        return f"https://x/admin/themes/{numeric}/editor", f"https://x/?preview_theme_id={numeric}"


class FakeOpenAI:
    def generate(self, api_key, *, prompt, model):
        return b"image-bytes"


def _setup(client):
    store = MemoryCredentialStore()
    client.app.state.credential_store = store
    shopify = FakeShopify()
    client.app.state.shopify_client = shopify
    client.app.state.openai_image_client = FakeOpenAI()
    return shopify, store


def _connect(client, auth_headers, domain="test.myshopify.com"):
    return client.post(
        f"{_BASE}/stores/connect",
        headers=auth_headers,
        json={
            "label": "My Store",
            "shop_domain": domain,
            "client_id": "cid",
            "client_secret": "csecret",
        },
    )


def _stage(client, auth_headers, store_id, **changes):
    payload = {
        "theme_id": "gid://shopify/Theme/1",
        "preset": "Minimal",
        "product_source": "catalog",
        "catalog_id": "cat_home",
        "ai_hero": False,
    }
    payload.update(changes)
    return client.post(f"{_BASE}/stores/{store_id}/plans", headers=auth_headers, json=payload)


# --- connect / secrets ------------------------------------------------------
def test_connect_stores_secrets_in_the_secure_store_not_the_db(client, auth_headers):
    _, secure = _setup(client)
    response = _connect(client, auth_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["connected"] is True
    assert body["shop_domain"] == "test.myshopify.com"
    assert "csecret" not in response.text

    with client.app.state.session_factory() as session:
        store = session.get(ShopifyStore, body["id"])
        credential = secure.get(store.credentials_ref)
        assert credential.username == "cid" and credential.password == "csecret"
        token = secure.get(store.token_ref)
        assert token.password == "tok-test.myshopify.com"


def test_delete_store_removes_secrets(client, auth_headers):
    _, secure = _setup(client)
    body = _connect(client, auth_headers).json()
    with client.app.state.session_factory() as session:
        refs = session.get(ShopifyStore, body["id"])
        credentials_ref, token_ref = refs.credentials_ref, refs.token_ref
    assert client.delete(f"{_BASE}/stores/{body['id']}", headers=auth_headers).status_code == 204
    assert secure.get(credentials_ref) is None
    assert secure.get(token_ref) is None


# --- capabilities gate staging ----------------------------------------------
def test_capability_map_blocks_ungranted_steps(client, auth_headers):
    shopify, _ = _setup(client)
    shopify.scopes = ["read_products"]  # nothing writable
    store_id = _connect(client, auth_headers).json()["id"]
    plan = _stage(client, auth_headers, store_id).json()
    steps = {s["key"]: s for s in plan["steps"]}
    assert steps["theme"]["status"] == "blocked" and steps["theme"]["reason"]
    assert steps["content"]["status"] == "blocked"
    assert steps["product_csv"]["status"] == "blocked"
    assert steps["analysis"]["status"] == "ready"


def test_staging_changes_nothing_remote(client, auth_headers):
    shopify, _ = _setup(client)
    store_id = _connect(client, auth_headers).json()["id"]
    shopify.calls.clear()
    plan = _stage(client, auth_headers, store_id).json()
    assert plan["status"] == "staged"
    assert [c for c in shopify.calls if c[0] in _MUTATIONS] == []


# --- execution --------------------------------------------------------------
def test_execute_requires_confirmation(client, auth_headers):
    _setup(client)
    store_id = _connect(client, auth_headers).json()["id"]
    plan_id = _stage(client, auth_headers, store_id).json()["id"]
    response = client.post(
        f"{_BASE}/stores/{store_id}/plans/{plan_id}/execute",
        headers=auth_headers,
        json={"confirm": False},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "confirm_required"


def test_execute_completes_and_theme_stays_a_draft(client, auth_headers):
    shopify, _ = _setup(client)
    store_id = _connect(client, auth_headers).json()["id"]
    plan_id = _stage(client, auth_headers, store_id).json()["id"]
    response = client.post(
        f"{_BASE}/stores/{store_id}/plans/{plan_id}/execute",
        headers=auth_headers,
        json={"confirm": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert all(step["status"] == "completed" for step in body["steps"])
    assert body["admin_url"] and body["preview_url"]
    # The theme was duplicated into a draft; there is no publish path at all.
    assert any(call[0] == "duplicate_theme" for call in shopify.calls)


def test_user_errors_fail_a_step_without_raising_and_reexecute_skips_completed(client, auth_headers):
    shopify, _ = _setup(client)
    shopify.page_errors = ["Page handle already taken"]
    store_id = _connect(client, auth_headers).json()["id"]
    plan_id = _stage(client, auth_headers, store_id).json()["id"]

    first = client.post(
        f"{_BASE}/stores/{store_id}/plans/{plan_id}/execute",
        headers=auth_headers,
        json={"confirm": True},
    )
    assert first.status_code == 200  # userErrors do not raise
    steps = {s["key"]: s for s in first.json()["steps"]}
    assert steps["content"]["status"] == "failed"
    assert "Page handle already taken" in steps["content"]["error"]
    assert first.json()["status"] == "partial"

    # Fix the cause and re-run: completed steps are skipped, only content retries.
    shopify.page_errors = []
    shopify.calls.clear()
    second = client.post(
        f"{_BASE}/stores/{store_id}/plans/{plan_id}/execute",
        headers=auth_headers,
        json={"confirm": True},
    ).json()
    assert not any(c[0] == "upsert_products" for c in shopify.calls)  # already completed → skipped
    assert any(c[0] == "upsert_pages" for c in shopify.calls)  # content retried
    assert {s["key"]: s["status"] for s in second["steps"]}["content"] == "completed"
    assert second["status"] == "completed"


def test_theme_file_upsert_bisects_to_isolate_a_bad_file(client, auth_headers):
    from manager_backend.features.shopify.pipeline import upsert_theme_files

    files = [{"key": f"assets/good{i}.css"} for i in range(4)] + [{"key": "bad.liquid"}]
    upserted: list[str] = []

    def batch_upsert(batch):
        keys = [f["key"] for f in batch]
        if "bad.liquid" in keys:
            return list(keys)  # Shopify rejects the whole batch atomically
        upserted.extend(keys)
        return []

    rejected = upsert_theme_files(files, batch_upsert, batch_size=50)
    assert rejected == ["bad.liquid"]
    assert set(upserted) == {f"assets/good{i}.css" for i in range(4)}


# --- ai settings / catalogs / csv -------------------------------------------
def test_ai_settings_never_return_the_key(client, auth_headers):
    _setup(client)
    assert client.get(f"{_BASE}/ai-images/settings").json() == {
        "enabled": False, "provider": "openai", "model": "gpt-image-1", "has_api_key": False,
    }
    updated = client.put(
        f"{_BASE}/ai-images/settings",
        headers=auth_headers,
        json={"enabled": True, "provider": "openai", "model": "gpt-image-1", "api_key": "sk-secret"},
    )
    assert updated.status_code == 200
    assert updated.json()["has_api_key"] is True
    assert "sk-secret" not in updated.text


def test_catalogs_and_csv_inspection(client, auth_headers):
    _setup(client)
    catalogs = client.get(f"{_BASE}/catalogs").json()
    assert any(c["id"] == "cat_home" for c in catalogs)

    store_id = _connect(client, auth_headers).json()["id"]
    csv_text = "Handle,Title,Variant Price\nfoo,Foo Widget,9.99\nbar,Bar Gadget,5.00\n"
    inspection = client.post(
        f"{_BASE}/stores/{store_id}/product-csv/inspect",
        headers=auth_headers,
        json={"content": csv_text},
    ).json()
    assert inspection["total"] == 2
    assert {"handle", "title", "price"} <= set(inspection["columns_mapped"])
    assert inspection["sample"][0]["title"] == "Foo Widget"
