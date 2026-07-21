# Manager Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a loopback-only FastAPI manager with authenticated requests, SQLite persistence, OpenAPI schemas, and profile/folder/tag/workflow-status CRUD.

**Architecture:** `manager_backend` is a feature-oriented Python package independent of the browser runtime. FastAPI routes call small services, services own transactions, SQLAlchemy models persist UTC timestamps and UUIDs, and Pydantic schemas define the canonical frontend contract. Runtime and proxy implementations plug into later service interfaces without changing v1 routes.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2, Alembic, SQLite WAL, httpx, pytest, pytest-asyncio.

## Global Constraints

- Bind only to `127.0.0.1`; never enable wildcard CORS.
- Prefix every application route with `/api/v1`.
- All IDs are UUID strings and API timestamps are UTC ISO-8601.
- Windows 10 and Windows 11 personas only; CloakBrowser Chromium only.
- Never return proxy passwords, authorization headers, cookies, tokens, or credential-bearing URLs.
- Store application data below `%LOCALAPPDATA%\CloakBrowser\Manager` unless tests inject a temporary root.
- Use the standard `{ "error": { "code", "message", "field_errors", "request_id" } }` envelope.
- New manager tests must run without browsers, network access, or Windows Credential Manager.
- Profile fields must follow `docs/PROFILE_FIELD_CAPABILITY_MATRIX.md`; website credentials, 2FA secrets, and unsupported independent fingerprint toggles are forbidden.

---

## File Structure

- `manager_backend/main.py`: application factory and lifespan.
- `manager_backend/config.py`: validated paths, origin, host, and token settings.
- `manager_backend/security.py`: install-token creation, bearer validation, origin validation, redaction.
- `manager_backend/errors.py`: typed application errors and FastAPI handlers.
- `manager_backend/db.py`: engine/session factory, WAL configuration, transaction dependency.
- `manager_backend/models.py`: foundation SQLAlchemy tables.
- `manager_backend/schemas/common.py`: pagination and error schemas.
- `manager_backend/features/catalog/`: folders, tags, and workflow-status schemas/service/routes.
- `manager_backend/features/profiles/`: profile schemas/service/routes.
- `manager_backend/api.py`: `/api/v1` router composition.
- `manager_backend/migrations/`: Alembic configuration and initial migration.
- `tests/manager/`: isolated unit and API contract tests.

### Task 1: Package and application security boundary

**Files:**
- Modify: `pyproject.toml`
- Create: `manager_backend/__init__.py`
- Create: `manager_backend/config.py`
- Create: `manager_backend/security.py`
- Create: `manager_backend/errors.py`
- Create: `manager_backend/main.py`
- Test: `tests/manager/test_security.py`
- Test: `tests/manager/test_health.py`

**Interfaces:**
- Produces: `ManagerSettings`, `create_app(settings: ManagerSettings | None = None) -> FastAPI`, `require_local_token`, and `redact_text(value: str) -> str`.

- [x] **Step 1: Write failing security tests**

```python
def test_health_rejects_missing_token(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_local_token"

def test_health_rejects_foreign_origin(client, auth_headers):
    response = client.get("/api/v1/health", headers={**auth_headers, "Origin": "https://evil.example"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_origin"

def test_redaction_removes_proxy_credentials():
    assert redact_text("socks5://user:secret@proxy.example:1080") == "socks5://***:***@proxy.example:1080"
```

- [x] **Step 2: Verify RED**

Run: `python -m pytest -q tests/manager/test_security.py tests/manager/test_health.py`
Expected: collection fails because `manager_backend` does not exist.

- [x] **Step 3: Implement the minimal application boundary**

Add the `manager` optional dependency group (`fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `pydantic-settings`, `keyring`, `psutil`) and the `manager-test` group (`httpx`). Implement settings with injected `data_root`, atomically create a 32-byte URL-safe install token with user-only intent, validate `Authorization: Bearer`, permit absent Origin for non-browser clients, require an exact configured Origin when present, and install safe error handlers.

- [x] **Step 4: Verify GREEN**

Run: `python -m pytest -q tests/manager/test_security.py tests/manager/test_health.py`
Expected: all tests pass with no network or browser launch.

- [x] **Step 5: Commit**

```text
git add pyproject.toml manager_backend tests/manager
git commit -m "feat(manager): add secure loopback API foundation"
```

### Task 2: SQLite session and initial schema

**Files:**
- Create: `manager_backend/db.py`
- Create: `manager_backend/models.py`
- Create: `manager_backend/migrations/env.py`
- Create: `manager_backend/migrations/script.py.mako`
- Create: `manager_backend/migrations/versions/0001_foundation.py`
- Create: `manager_backend/alembic.ini`
- Test: `tests/manager/test_database.py`

**Interfaces:**
- Produces: `Base`, `create_engine_for(settings)`, `session_scope()`, and model classes `Profile`, `Folder`, `Tag`, `ProfileTag`, `WorkflowStatus`.

- [x] **Step 1: Write failing persistence tests**

```python
def test_sqlite_uses_wal(database_engine):
    with database_engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"

def test_profile_name_and_seed_persist(session, profile_factory):
    profile = profile_factory(name="Account A", fingerprint_seed="18446744073709551615")
    session.commit()
    session.expire_all()
    assert session.get(Profile, profile.id).fingerprint_seed == "18446744073709551615"
```

- [x] **Step 2: Verify RED**

Run: `python -m pytest -q tests/manager/test_database.py`
Expected: import failure for `manager_backend.db`.

- [x] **Step 3: Implement models and migration**

Use SQLAlchemy 2 typed mappings, UUID strings, UTC-aware timestamp helpers, foreign keys with explicit delete behavior, uniqueness for catalog names, JSON stored as validated text, soft deletion on profiles, and SQLite connect hooks enabling WAL and foreign keys.

- [x] **Step 4: Verify migration and GREEN**

Run: `python -m alembic -c manager_backend/alembic.ini upgrade head` with `CLOAK_MANAGER_DATA_ROOT` pointing to a temporary directory, then `python -m pytest -q tests/manager/test_database.py`.
Expected: migration succeeds and tests pass.

- [x] **Step 5: Commit**

```text
git add manager_backend tests/manager
git commit -m "feat(manager): add SQLite foundation schema"
```

### Task 3: Canonical schemas and error envelope

**Files:**
- Modify: `manager_backend/models.py`
- Create: `manager_backend/migrations/versions/0002_capability_profile_fields.py`
- Create: `manager_backend/fingerprints.py`
- Create: `manager_backend/schemas/__init__.py`
- Create: `manager_backend/schemas/common.py`
- Create: `manager_backend/features/profiles/schemas.py`
- Create: `manager_backend/features/catalog/schemas.py`
- Test: `tests/manager/test_schemas.py`

**Interfaces:**
- Produces: `ProfileCreate`, `ProfilePatch`, `ProfileRead`, `ProfilePage`, `FolderCreate`, `TagCreate`, `WorkflowStatusCreate`, and `ErrorEnvelope`.

- [x] **Step 1: Write failing schema tests**

```python
def test_profile_rejects_platform_override():
    with pytest.raises(ValidationError):
        ProfileCreate(name="A", platform="macos", fingerprint_seed="1")

def test_seed_must_be_unsigned_64_bit_decimal():
    with pytest.raises(ValidationError):
        ProfileCreate(name="A", fingerprint_seed="18446744073709551616")

def test_profile_rejects_password_vault_fields():
    with pytest.raises(ValidationError):
        ProfileCreate(name="A", password="secret")

def test_fingerprint_seed_and_hash_are_stable():
    first = build_fingerprint_identity(seed="42", location=LocationSettings())
    second = build_fingerprint_identity(seed="42", location=LocationSettings())
    assert first.config_hash == second.config_hash

def test_different_seeds_have_different_config_hashes():
    assert build_fingerprint_identity(seed="1").config_hash != build_fingerprint_identity(seed="2").config_hash
```

- [x] **Step 2: Verify RED**

Run: `python -m pytest -q tests/manager/test_schemas.py`
Expected: schema imports fail.

- [x] **Step 3: Implement exact v1 schemas**

Migrate the profile model from generic identity/hardware/advanced columns to the exact startup URL, browser identity, location, window, and behavior fields in the capability matrix. Add a unique database constraint for the seed, fingerprint revision `1`, canonical JSON hashing, and collision-safe secure seed allocation. Forbid unknown write fields, trim names, validate structured groups, constrain page size to 1–100, keep seed as decimal text, expose runtime state as `stopped` until the runtime subsystem is installed, and omit every secret-bearing field.

- [x] **Step 4: Verify GREEN**

Run: `python -m pytest -q tests/manager/test_schemas.py`
Expected: all validation and serialization tests pass.

- [x] **Step 5: Commit**

```text
git add manager_backend tests/manager
git commit -m "feat(manager): define canonical API schemas"
```

### Task 4: Catalog CRUD services and routes

**Files:**
- Create: `manager_backend/features/catalog/service.py`
- Create: `manager_backend/features/catalog/routes.py`
- Modify: `manager_backend/api.py`
- Test: `tests/manager/test_catalog_api.py`

**Interfaces:**
- Produces authenticated CRUD under `/api/v1/folders`, `/tags`, `/workflow-statuses` and `/reorder` endpoints accepting `{ "ids": [uuid] }`.

- [x] **Step 1: Write failing API tests**

```python
def test_folder_crud(client, auth_headers):
    created = client.post("/api/v1/folders", headers=auth_headers, json={"name": "KYC"})
    assert created.status_code == 201
    folder_id = created.json()["id"]
    assert client.patch(f"/api/v1/folders/{folder_id}", headers=auth_headers, json={"name": "Primary"}).json()["name"] == "Primary"

def test_duplicate_folder_uses_safe_error(client, auth_headers):
    client.post("/api/v1/folders", headers=auth_headers, json={"name": "KYC"})
    response = client.post("/api/v1/folders", headers=auth_headers, json={"name": "KYC"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "folder_name_conflict"
```

- [x] **Step 2: Verify RED**, run `python -m pytest -q tests/manager/test_catalog_api.py`, and confirm 404 responses.
- [x] **Step 3: Implement transactional catalog services, deterministic positions, conflict translation, referential checks, and authenticated routes.**
- [x] **Step 4: Verify GREEN** with `python -m pytest -q tests/manager/test_catalog_api.py`.
- [x] **Step 5: Commit** with `git commit -m "feat(manager): add catalog CRUD APIs"` after staging the catalog files and tests.

### Task 5: Profile CRUD, filters, duplicate, fingerprint regeneration, and trash

**Files:**
- Create: `manager_backend/features/profiles/service.py`
- Create: `manager_backend/features/profiles/routes.py`
- Modify: `manager_backend/api.py`
- Test: `tests/manager/test_profiles_api.py`

**Interfaces:**
- Produces: profile list/create/read/patch, quick-create, duplicate, regenerate-fingerprint, move-to-trash, restore, and bulk operations. Runtime commands remain explicit `501 runtime_not_available` until subsystem 2 replaces the adapter.

- [x] **Step 1: Write failing profile lifecycle tests**

```python
def test_create_list_patch_and_trash_profile(client, auth_headers):
    created = client.post("/api/v1/profiles", headers=auth_headers, json={"name": "Account A", "startup_urls": ["https://example.com"]})
    assert created.status_code == 201
    profile_id = created.json()["id"]
    assert client.get("/api/v1/profiles?query=Account", headers=auth_headers).json()["total"] == 1
    assert client.patch(f"/api/v1/profiles/{profile_id}", headers=auth_headers, json={"pinned": True}).json()["pinned"] is True
    assert client.post(f"/api/v1/profiles/{profile_id}/move-to-trash", headers=auth_headers).status_code == 200

def test_duplicate_gets_new_seed(client, auth_headers, created_profile):
    duplicate = client.post(f"/api/v1/profiles/{created_profile['id']}/duplicate", headers=auth_headers).json()
    assert duplicate["id"] != created_profile["id"]
    assert duplicate["fingerprint_seed"] != created_profile["fingerprint_seed"]
```

- [x] **Step 2: Verify RED**, run `python -m pytest -q tests/manager/test_profiles_api.py`, and confirm missing routes.
- [x] **Step 3: Implement services with `secrets.randbits(64)`, soft-delete defaults, filter composition, allowlisted sorting, transactional tag replacement, and safe bulk limits.**
- [x] **Step 4: Verify GREEN** with `python -m pytest -q tests/manager/test_profiles_api.py`.
- [x] **Step 5: Commit** with `git commit -m "feat(manager): add profile management APIs"` after staging profile files and tests.

### Task 6: Bootstrap, version, OpenAPI fixture, and foundation verification

**Files:**
- Modify: `manager_backend/main.py`
- Modify: `manager_backend/api.py`
- Create: `manager_backend/openapi.json`
- Create: `tests/manager/test_contract.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `/api/v1/health`, `/app/bootstrap`, `/app/version`, stable operation IDs, checked-in `manager_backend/openapi.json`, and local run instructions.

- [x] **Step 1: Write failing contract tests**

```python
def test_openapi_has_required_foundation_routes(app):
    paths = app.openapi()["paths"]
    assert "/api/v1/profiles" in paths
    assert "/api/v1/folders" in paths
    assert "/api/v1/app/bootstrap" in paths

def test_every_error_response_references_error_envelope(app):
    document = app.openapi()
    assert "ErrorEnvelope" in document["components"]["schemas"]
```

- [x] **Step 2: Verify RED** with `python -m pytest -q tests/manager/test_contract.py`.
- [x] **Step 3: Implement bootstrap/version payloads, deterministic OpenAPI generation, and README commands using `127.0.0.1`.**
- [x] **Step 4: Generate the fixture with `python -m manager_backend.export_openapi` and run `python -m pytest -q tests/manager` plus `python -m pytest -q -m "not slow" tests/test_config.py tests/test_build_args.py tests/test_proxy.py`.**
- [x] **Step 5: Commit** with `git commit -m "docs(manager): publish foundation API contract"` after staging the fixture, docs, and tests.

## Self-Review Results

- Spec coverage: foundation security, persistence, catalogs, profile CRUD, filters, errors, bootstrap, and canonical OpenAPI are covered. Browser runtime/WebSocket and proxy/diagnostics are intentionally assigned to the next two subsystem plans.
- Placeholder scan: no deferred implementation language exists inside foundation tasks; runtime endpoints return an explicit typed adapter error until the runtime subsystem installs them.
- Type consistency: profile seeds remain unsigned 64-bit decimal strings across schema, model, service, and API; all catalog and profile IDs remain UUID strings.
