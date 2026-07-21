# Profile-Owned Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attach one credential-safe proxy configuration directly to each profile, with parsing, quick testing, and asynchronous quality reports but no separate proxy inventory.

**Architecture:** Profile proxy metadata is stored in a validated JSON column while credentials live behind a Windows Credential Manager abstraction. Injected adapters keep tests offline and reuse the existing scanner in production.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, keyring, existing proxy scanner, pytest.

## Global Constraints

- No proxy CRUD list, proxy paging, shared assignment, or reusable proxy record table.
- Never serialize or log credentials, authenticated URLs, credential references, or raw parse input.
- Every profile owns at most one proxy configuration.
- Tests require no network, browser, or real Windows Credential Manager.

### Task 1: Parser and credential boundary

**Files:** Create `manager_backend/features/profile_proxy/{credentials.py,parser.py,schemas.py}` and tests `test_profile_proxy_parser.py`, `test_profile_proxy_credentials.py`.

- [ ] Write failing tests for supported formats, unsafe rejection, single percent decoding, fake-keyring round trips, malformed storage, and sanitized provider failures.
- [ ] Implement `ParsedProxy`, `ProxyCredential`, `CredentialStore`, `MemoryCredentialStore`, and `KeyringCredentialStore`.
- [ ] Run focused tests and commit `feat(manager): add profile proxy security boundary`.

### Task 2: Profile schema, persistence, and edit behavior

**Files:** Modify profile models/schemas/service/routes and app injection; create migration `0005_profile_owned_proxy.py`; add API and migration tests.

- [ ] Write failing tests for create/read/patch/direct transition, write-only secrets, preservation/replacement/clear compensation, duplicate-without-secret behavior, trash restoration, and migration.
- [ ] Add validated `proxy_config_json`, remove `proxy_id`, inject credential store, and implement profile-owned proxy updates.
- [ ] Add authenticated `POST /api/v1/profiles/proxy/parse`.
- [ ] Add smart bulk preview/apply tests and endpoints with explicit mapping, one-to-all warning, opt-in round robin, unused-line reporting, 100-row bounds, and safe partial failures.
- [ ] Run profile/security/migration tests and commit `feat(manager): attach proxies to profiles`.

### Task 3: Quick Test

**Files:** Create `manager_backend/features/profile_proxy/testing.py`; modify profile proxy routes/service; add `test_profile_proxy_quick_test.py`.

- [ ] Write failing tests for safe success caching, exit-IP disagreement, direct mode, missing credentials, 20-second budget, and safe error categories.
- [ ] Implement injected `ProxyQuickTester` and the authenticated quick-test endpoint using existing connectivity intelligence in production.
- [ ] Run focused and proxy-intelligence tests; commit `feat(manager): test profile proxy connectivity`.

### Task 4: Quality runs

**Files:** Add quality model/migration `0006_profile_proxy_quality_runs.py`, runner, routes, lifecycle tests, and migration tests.

- [ ] Write failing tests for queued/running/completed/failed lifecycle, single-active-run conflict, restart recovery, safe reports/artifacts, and redaction.
- [ ] Implement bounded background execution over `run_proxy_quality_scan` and report endpoints.
- [ ] Run manager plus existing scanner/relay/site-check tests; commit `feat(manager): add profile proxy quality reports`.

### Task 5: Contract and integration

**Files:** Update bootstrap capability, OpenAPI, README, canonical manager design, and contract tests.

- [ ] Verify write-only input credentials and secret-free read/report schemas.
- [ ] Regenerate OpenAPI and run all manager/proxy regressions plus migration drift.
- [ ] Commit `docs(manager): publish profile proxy contract`, push the feature branch, merge through a clean worktree, verify, and push main.
