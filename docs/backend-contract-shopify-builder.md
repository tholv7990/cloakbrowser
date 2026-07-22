# Backend contract — Shopify Builder (connect → analyze → stage → draft build)

**Owner:** backend (Codex). Frontend (nav item + connect/plan/execute screens) built afterward by the frontend agent.

**Reference implementation:** `Quantum-Source-Clean-*/backend/services/shopify_builder_service.py` (the orchestrator, ~116KB) and `backend/services/shopify_builder/{analysis,content,navigation,design,pipeline}.py`, `backend/api/shopify_builder.py`, `frontend/src/pages/ShopifyBuilder.tsx`. Read those for exact GraphQL bodies and the content/design templates — this doc adapts them to `manager_backend`.

## Goal

Connect a Shopify store, auto-detect its niche + language, map products (CSV or a built-in catalog), **stage** a build plan (nothing changes on Shopify yet), then **execute** it — creating products, pages, policies, menus, and a **draft (unpublished) theme** with an injected design system + optional AI hero. Full scope: stores, capability inspection, product mapping, content/policies/navigation, draft theme build, AI images, staged idempotent pipeline.

Almost entirely backend + external API — **no Playwright, no runtime layer**. Drops cleanly into `manager_backend`.

## Non-negotiables (our constraints)

- **Draft-only. Never publish.** Theme role stays `UNPUBLISHED`; execute requires `{confirm:true}`; the live/main theme is never modified.
- **Secrets to the secure store, never DB plaintext.** Per-store OAuth `client_id`/`client_secret`, the fetched access token, and the OpenAI API key go in the existing `CredentialStore` (or an equivalent secure store), referenced by key; DB holds only refs + non-secret metadata (scopes, shop info, token expiry). Mask in all API payloads (Quantum masks in SQLite; we keep secrets out of the DB entirely).
- **SQLAlchemy + Alembic**, `StrictModel`, `/api/v1` prefix, session/origin auth.
- New capability flag **`shopify_builder`** in `AppCapabilities` (frontend nav-gates on it).

## External services

- **Shopify Admin GraphQL API**, version pinned in config, env-overridable (`SHOPIFY_API_VERSION`, Quantum default `"2026-07"`). Endpoint `https://{shop_domain}/admin/api/{ver}/graphql.json`.
- **Auth = OAuth client-credentials grant** → `POST https://{domain}/admin/oauth/access_token` with `{client_id, client_secret, grant_type:"client_credentials"}` → access token + granted scopes; cache token+expiry+scopes per store, refresh when stale (`shopify_builder_service.py:488`).
- **OpenAI Images** for the hero: `POST https://api.openai.com/v1/images/generations`, model configurable (Quantum hard-pins `gpt-image-2`, `1536x1024`, jpeg — make provider/model a setting, default to a current model). Decode `b64_json` → bytes.
- HTTP via `requests`/`httpx`. Mutations used: `productSet`, `pageCreate`/`pageUpdate`, `shopPolicyUpdate`, `menuCreate`/`menuUpdate`, `themeDuplicate`, `themeFilesUpsert`, `themeFilesDelete`, plus theme-file read queries.

## Data model (SQLAlchemy + Alembic)

- `shopify_store` — `id`, `label`, `shop_domain`, `scopes_json`, `shop_info_json`, `inspection_json`, `proxy_id` (nullable), `credentials_ref` (→ secure store: client id/secret), `token_ref` (→ secure store), `token_expires_at`, `created_at`, `updated_at`.
- `shopify_store_profile` — `store_id`, brand/niche/language overrides (`niche`, `language`, `store_name`, `support_email`, ...). May be folded into `shopify_store` as JSON.
- `shopify_ai_settings` — single row: `provider`, `model`, `enabled`, `api_key_ref` (→ secure store).
- `shopify_build_plan` — `id`, `store_id`, `status` (`staged|running|completed|partial|failed`), `mode` (`"draft_only"`), `config_json` (resolved theme/preset/products/design/analysis snapshot), `created_at`.
- `shopify_plan_step` — `id`, `plan_id`, `key`, `status` (`planned|ready|blocked|running|completed|failed`), `reason`, `result_json`, `error`, `attempts`, `order`.

## HTTP surface (`features/shopify/routes.py`, prefix `/api/v1/shopify-builder`)

Stores: `GET /stores`, `POST /stores/connect` (`{label, shop_domain, client_id, client_secret, proxy_id}`), `POST /stores/{id}/inspect`, `PUT /stores/{id}/network-route` (`{proxy_id}`), `DELETE /stores/{id}`, `GET/PUT /stores/{id}/profile`.
AI: `GET /ai-images/settings` (masked), `PUT /ai-images/settings`.
Themes: `POST /themes/inspect`, `GET /stores/{id}/themes/library`.
Products: `POST /stores/{id}/product-csv/inspect`, `GET /catalogs`, `POST /stores/{id}/product-csv/catalogs/{catalog_id}`.
Plans: `POST /stores/{id}/plans` (stage), `GET /stores/{id}/plans/{plan_id}`, `POST /stores/{id}/plans/{plan_id}/execute` (`{confirm}`).

## Backend mechanisms (port from Quantum)

1. **Per-store proxy routing** (`shopify_builder_service.py:411`). A store egresses through a saved proxy so Shopify sees a consistent IP. Quantum uses a `ContextVar` + `requests` `proxies=` spread on every call, wrapped by `_use_shopify_network_route(proxy_id)`. **Our upgrade path:** route Shopify HTTP through our own proxy stack for a more coherent fingerprint than a bare proxied client — but the `requests`-proxies `ContextVar` pattern is a fine v1.
2. **Token cache + capability mapping** (`:488, 582`). Cache the client-credentials token per store; refresh when `token_expires_at` is stale. Map granted scopes → capability booleans (`write_products`, `write_legal_policies`, `write_navigation`, theme-write, ...) incl. a theme-write exemption flag.
3. **Analysis** (`shopify_builder/analysis.py:105`). `detect_language`: manual override → address hints → country → timezone → English. `detect_niche`: built-in catalog id (confidence 1.0) → keyword scoring over product title/type/vendor/handle → product_type → "General store". Simple lookup/keyword tables.
4. **Product mapping** (`shopify_builder_service.py:1906`). CSV via `PRODUCT_COLUMN_ALIASES` (maps Shopify-export or generic headers), or a **built-in catalog**. Upsert via `productSet(input, identifier:{handle}, synchronous:true)` — idempotent by handle; build `productOptions` from variant options (default single "Title/Default Title"); tags split on `,`/`|`; images passed as `files[]` `originalSource` URLs Shopify fetches.
5. **Staged, idempotent, resumable pipeline** (`pipeline.py`, `_run_plan_step`). `build_plan_steps` renders each step `ready|blocked|planned` with a human reason from capabilities. `create_build_plan` re-inspects the store, resolves theme+preset, parses products, runs analysis (manual niche wins), builds the design config + AI settings, persists plan `status='staged'` + one `plan_step` row per step. Execution (`_run_plan_step`, ~40 lines — copy it) flips a step `running` → runs → persists `completed|failed` + result JSON, and **skips already-completed steps** so partial builds re-run safely; GraphQL `userErrors` become step errors without raising. Step order: `product_csv` → `analysis` → `identity` → `content` (pages) → `policies` → `navigation` → `preset` → `design` → `theme`.
6. **Content generation** (`content.py`). 8 legal policies + 5 info pages (About/FAQ/Contact/Track/…) as localized HTML (EN/DE/FR/ES) → `pageCreate`/`pageUpdate` + `shopPolicyUpdate` (gated on `write_legal_policies`). **This ~350 lines of templates is the real asset** — adapt to our brand voice.
7. **Navigation** (`navigation.py`). Build/upsert main+footer+policies menus via `menuCreate`/`menuUpdate` (gated on `write_navigation`).
8. **Draft theme build** (`shopify_builder_service.py:2296`). Reuse an existing unpublished draft named `CloakBrowser - {store} - {preset}` or **`themeDuplicate`** the MAIN theme; wait for processing; read source files (local folder/zip or remote read query); apply the design; **`themeFilesUpsert` in batches of 50, liquid-before-json, with recursive bisection on failure** to isolate a bad file; prune stale files only if nothing was rejected/deferred. Role stays `UNPUBLISHED`; return `admin_url` + `preview_url` (`?preview_theme_id=`). Never replace the base theme.
9. **Design system injection** (`design.py:185`). Swap `layout/theme.liquid` (strip prior blocks, inject a CSS `<link>` + design-token `<style>` into `<head>`, and `{% render '...footer' %}` before the footer), write `assets/*-storefront.css`, `sections/*-storefront.liquid`, `snippets/*-footer.liquid`, optional `assets/*-hero.jpg`, and a fresh `templates/index.json` pointing the homepage at the new section. Colors are **WCAG-normalized** (`normalize_design_contrast`, `design.py:21`): recompute every foreground from the actual background by relative-luminance contrast ratio — never trust a supplied foreground.
10. **AI hero** (`design.py:12-141`). Niche → design recipe (palette/copy/image-prompt) → wide, text-free, negative-space-left editorial prompt seeded with product names → OpenAI images → write bytes atomically to a per-plan build dir. If AI disabled, Liquid falls back to the first collection product image.

## Frontend (built afterward by the frontend agent)

New **Shopify** nav item + screen, gated by `shopify_builder`. Connect wizard, capability grid, theme + product-CSV/catalog pickers, AI-image settings, **stage plan** (preview, nothing changes), then a `confirm` + **execute** (drafts) with per-step status, and `admin_url`/`preview_url` links. Full EN/VI. — Listed for end-to-end understanding; not Codex's job.

## Suggested build order

1. Store connect + token cache + inspect + capability map (`GET /stores`, `/connect`, `/inspect`).
2. The staged/idempotent **plan model + `_run_plan_step`** wrapper (underpins everything).
3. Product mapping (CSV/catalog) + `productSet`.
4. Content + policies + navigation.
5. Draft theme build (duplicate + batched upsert) + design injection.
6. AI hero + settings.

## Tests

`tests/manager/test_shopify_*.py` (mock the Shopify GraphQL + OpenAI HTTP): store connect stores secrets to the secure store (not DB); capability map gates blocked steps; `create_build_plan` changes nothing remote; `execute` requires `confirm`; `_run_plan_step` skips completed steps and records `userErrors` as failures without raising; theme build never sets role `PUBLISHED`; batched upsert bisects on a failing file. Update `openapi.json` if checked in.
