# Manager Proxy Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add credential-safe reusable proxy CRUD, parsing, quick tests, and asynchronous quality reports to the authenticated Windows profile manager.

**Architecture:** Proxy metadata and sanitized test summaries live in SQLite, while a `CredentialStore` abstraction writes username/password JSON to Windows Credential Manager. Network operations sit behind injected adapters so the manager test suite remains offline; production adapters reuse `benchmarks.proxy_intelligence` and `benchmarks.proxy_quality`.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, keyring/Windows Credential Manager, httpx/SOCKS, existing proxy scanner, pytest.

## Global Constraints

- Never store or log proxy usernames, passwords, authenticated URLs, or raw parse input.
- All routes require owner authentication; mutations require exact Origin and CSRF.
- Manager unit tests require no network, browser, or real Windows Credential Manager.
- Schemes are exactly `direct`, `http`, `https`, `socks5`, and `socks5h`.
- Quick tests have a 20-second total budget; quality tests are asynchronous and never solve CAPTCHAs.

---

### Task 1: Credential abstraction and strict proxy parser

**Files:**
- Create: `manager_backend/features/proxies/credentials.py`
- Create: `manager_backend/features/proxies/parser.py`
- Create: `manager_backend/features/proxies/schemas.py`
- Test: `tests/manager/test_proxy_parser.py`
- Test: `tests/manager/test_proxy_credentials.py`

**Interfaces:**
- Produces `ProxyCredential(username: str, password: str)`.
- Produces `CredentialStore.put(ref, credential)`, `.get(ref)`, and `.delete(ref)` plus `KeyringCredentialStore`.
- Produces `parse_proxy(value: str) -> ParsedProxy` with scheme, host, port, username, and password.

- [ ] Write parser tests for all approved URL/colon formats, percent decoding, bracketed IPv6, default SOCKS5, and rejection of paths, control characters, partial credentials, invalid ports, and ambiguous IPv6.
- [ ] Run `pytest tests/manager/test_proxy_parser.py -q` and confirm missing modules.
- [ ] Implement strict schemas and parser without DNS or network access.
- [ ] Write credential tests using a fake keyring backend, including malformed stored JSON and provider exceptions mapped to `credential_store_unavailable`.
- [ ] Implement keyring service `cloakbrowser-manager-proxy`; never include provider exception text in `ManagerError`.
- [ ] Run both focused test files and commit `feat(manager): add secure proxy parsing and credentials`.

### Task 2: Proxy persistence and CRUD API

**Files:**
- Modify: `manager_backend/models.py`
- Create: `manager_backend/migrations/versions/0005_proxy_management.py`
- Create: `manager_backend/features/proxies/service.py`
- Create: `manager_backend/features/proxies/routes.py`
- Modify: `manager_backend/api.py`
- Modify: `manager_backend/main.py`
- Modify: `manager_backend/features/profiles/service.py`
- Test: `tests/manager/test_proxy_api.py`
- Test: `tests/manager/test_proxy_migration.py`

**Interfaces:**
- Produces safe proxy list/detail/create/patch/delete/parse routes under `/api/v1/proxies`.
- Produces `resolve_proxy_url(db, credential_store, proxy_id) -> str | None` for runtime and tests.

- [ ] Write failing authenticated API tests for parse, create/read/list/update, credential preservation/replacement/clear, no-secret serialization, duplicate labels, direct records, pagination, and referenced-delete rejection.
- [ ] Run the API tests and confirm missing routes.
- [ ] Add `Proxy` model, profile foreign key/relationship, migration `0005`, service compensation logic, and routes.
- [ ] Inject `app.state.credential_store`; production defaults to `KeyringCredentialStore`, tests use `MemoryCredentialStore`.
- [ ] Write and run migration preservation plus upgrade/downgrade tests.
- [ ] Run CRUD, profile, database, and security tests; commit `feat(manager): add reusable proxy management APIs`.

### Task 3: Bounded quick proxy testing

**Files:**
- Create: `manager_backend/features/proxies/testing.py`
- Modify: `manager_backend/features/proxies/routes.py`
- Modify: `manager_backend/features/proxies/service.py`
- Test: `tests/manager/test_proxy_quick_test.py`

**Interfaces:**
- Produces `ProxyQuickTester.run(proxy_url: str, timeout_seconds: float = 20) -> QuickTestResult`.
- Production `ScannerQuickTester` reuses `resolve_exit_ip` and safe intelligence lookup; tests inject a fake.

- [ ] Write failing tests for success caching, two-echo disagreement, 20-second adapter budget, safe timeout/auth/DNS/refused/upstream error mapping, direct mode, missing credentials, and response redaction.
- [ ] Implement the injected quick-test adapter and `POST /api/v1/proxies/{id}/quick-test`.
- [ ] Persist only safe result fields and return `proxy_test_failed` with a safe category when connectivity fails.
- [ ] Run focused and scanner regression tests; commit `feat(manager): add bounded proxy quick tests`.

### Task 4: Asynchronous quality runs and reports

**Files:**
- Modify: `manager_backend/models.py`
- Create: `manager_backend/migrations/versions/0006_proxy_quality_runs.py`
- Create: `manager_backend/features/proxies/quality.py`
- Modify: `manager_backend/features/proxies/schemas.py`
- Modify: `manager_backend/features/proxies/routes.py`
- Modify: `manager_backend/main.py`
- Test: `tests/manager/test_proxy_quality_api.py`
- Test: `tests/manager/test_proxy_quality_migration.py`

**Interfaces:**
- Produces `QualityRunner.submit(run_id, proxy_id)`, with production execution invoking `run_proxy_quality_scan` and tests using a deterministic fake.
- Produces quality-test HTTP 202, per-proxy report list, and `/api/v1/proxy-reports/{run_id}` detail.

- [ ] Write failing tests for queued/running/completed/failed states, one-active-run conflict, safe summaries/artifact links, secret rejection, missing reports, and orphan recovery after restart.
- [ ] Add `ProxyQualityRun` persistence and migration `0006`.
- [ ] Implement a bounded manager-owned executor, scanner adapter, sanitized artifact-root validation, and startup orphan recovery.
- [ ] Run API/migration tests and existing scanner/relay/site-check tests; commit `feat(manager): add proxy quality reports`.

### Task 5: Frontend contract and final verification

**Files:**
- Modify: `manager_backend/features/app/routes.py`
- Regenerate: `manager_backend/openapi.json`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-21-windows-profile-manager-design.md`
- Test: `tests/manager/test_proxy_contract.py`

**Interfaces:**
- Sets bootstrap `proxy_management=true` and exposes canonical proxy schemas/operation IDs to Claude Code.

- [ ] Add failing contract tests for write-only credential inputs, absence of secrets in read/report schemas, error envelopes, operation IDs, and enabled bootstrap capability.
- [ ] Update bootstrap, README, and canonical manager design; regenerate OpenAPI.
- [ ] Run all manager tests plus existing proxy scanner regressions and migration drift checks.
- [ ] Commit `docs(manager): publish proxy management contract`, push the backend branch, merge through a clean integration worktree, verify, and push main.
