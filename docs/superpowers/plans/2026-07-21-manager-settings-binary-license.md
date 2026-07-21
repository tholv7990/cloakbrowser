# Manager Settings and Binary License Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace mock-only Manager settings with authenticated backend persistence and accurate live CloakBrowser binary/license reporting.

**Architecture:** Store only non-secret owner preferences in a small JSON document under the Manager data root using atomic replacement. Compose each settings response with read-only facts from `cloakbrowser.binary_info()` and license helpers; never persist or return the license key. Keep update checks as an explicit authenticated mutation and make the frontend refresh the settings query afterward.

**Tech Stack:** FastAPI, Pydantic, pathlib/JSON, pytest, React Query, TypeScript/Vitest.

## Global Constraints

- Windows-only local single-owner Manager.
- License keys remain environment-only and must never enter SQLite, settings JSON, logs, or API responses.
- Browser paths and version/update state come from runtime resolution, never fixtures.
- All mutations retain the existing session-cookie and CSRF protection.
- Existing proxy/profile/runtime contracts must remain compatible.

---

### Task 1: Settings persistence and schemas

**Files:**
- Create: `manager_backend/features/settings/schemas.py`
- Create: `manager_backend/features/settings/store.py`
- Test: `tests/manager/test_settings_store.py`

**Interfaces:**
- Produces: `ManagerPreferences`, `SettingsPatch`, and `SettingsStore.load()/patch()`.
- Persists: locale, timezone, proxy-test default, rows/page, theme, and retention values.

- [ ] Write tests proving defaults load when absent, patches survive a new store instance, unknown fields are rejected, and writes are atomic.
- [ ] Run `python -m pytest tests/manager/test_settings_store.py -q` and verify the tests fail because the feature is absent.
- [ ] Implement strict validated models and an atomic temporary-file replacement store.
- [ ] Rerun the focused tests and verify they pass.

### Task 2: Live binary/license facts and authenticated routes

**Files:**
- Create: `manager_backend/features/settings/service.py`
- Create: `manager_backend/features/settings/routes.py`
- Modify: `manager_backend/api.py`
- Modify: `manager_backend/main.py`
- Modify: `manager_backend/features/app/routes.py`
- Test: `tests/manager/test_settings_api.py`

**Interfaces:**
- Produces: `GET /settings`, `PATCH /settings`, and `POST /settings/browser/check-update`.
- Consumes: `cloakbrowser.binary_info`, `resolve_license_key`, `validate_license`, `get_active_session_count`, `check_for_update`, and `check_for_pro_update` through injected callables for deterministic tests.

- [ ] Write API tests for authentication, CSRF, real resolved paths, free/Pro tier metadata, absence of license secrets, persistence, and update refresh.
- [ ] Run the focused API tests and verify missing-route failures.
- [ ] Implement response composition and routes with update errors surfaced as safe Manager errors.
- [ ] Enable the settings capability and regenerate `manager_backend/openapi.json`.
- [ ] Rerun focused tests and verify they pass.

### Task 3: Frontend contract wiring

**Files:**
- Modify: `manager/frontend/src/types/api.ts`
- Modify: `manager/frontend/src/api/adapter.ts`
- Modify: `manager/frontend/src/api/real.ts`
- Modify: `manager/frontend/src/features/settings/api.ts`
- Modify: `manager/frontend/src/features/settings/SettingsPage.tsx`
- Modify: `manager/frontend/src/mocks/data.ts`
- Modify: `manager/frontend/src/mocks/mockApi.ts`
- Test: `manager/frontend/src/mocks/mockApi.test.ts`

**Interfaces:**
- Consumes: the settings endpoints from Task 2.
- Produces: a Settings screen showing actual tier, binary version/path, installed state, latest entitled version, update status, and active/maximum sessions.

- [ ] Write a failing frontend test proving update checking refreshes displayed browser facts.
- [ ] Run the focused Vitest test and verify the expected failure.
- [ ] Extend types and adapters, then replace the current `/app/version` refetch with the real update mutation.
- [ ] Keep mock mode schema-compatible while making its values clearly fixtures.
- [ ] Run frontend tests and typecheck.

### Task 4: Full verification and documentation

**Files:**
- Modify: `docs/frontend-backend-contract-questions.md`
- Modify: `manager/frontend/README.md`

**Interfaces:**
- Documents: real settings endpoints, secret-handling rules, and free/Pro display semantics.

- [ ] Run `python -m pytest tests/manager -q`.
- [ ] Run `npm test -- --run`, `npm run typecheck`, and `npm run build` in `manager/frontend`.
- [ ] Run the OpenAPI contract test and confirm no schema drift.
- [ ] Review the diff for fixture paths, license-key exposure, placeholders, and unrelated changes.
- [ ] Commit the verified feature on `feature/settings-binary-license`.
