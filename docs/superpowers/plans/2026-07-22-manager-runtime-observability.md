# Manager Runtime Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add sanitized profile logs, real runtime counts, safe profile-directory actions, and conflict-safe partial profile updates.

**Architecture:** Extend the existing SQLAlchemy/runtime feature boundaries. Centralize log sanitization and directory containment in focused services; keep routes thin. Patch schemas use Pydantic provided-field tracking and the service enforces optimistic concurrency.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, React 19, TypeScript, TanStack Query, Vitest.

## Global Constraints

- Windows-only directory opening; paths always derive from `ManagerSettings.data_root`.
- Never expose credentials, cookies, license/session tokens, process environments, or arbitrary command lines.
- Runtime-active means `starting`, `running`, or `stopping`.
- Profile log retention is 2,000 rows per profile; API page size maximum is 200.
- AI management remains out of scope.

---

### Task 1: Persist and sanitize profile logs

**Files:**
- Modify: `manager_backend/models.py`
- Create: `manager_backend/migrations/versions/0008_runtime_observability.py`
- Create: `manager_backend/features/runtime/logs.py`
- Test: `tests/manager/test_runtime_logs.py`

**Interfaces:**
- Produces: `append_profile_log(session, profile_id, level, event, *, fields, settings) -> ProfileLogEntry` and `list_profile_logs(...) -> Page`. `settings` is the trusted path authority; the service derives profile directories from `settings.data_root` and never accepts a caller-provided root.

- [ ] Write failing tests proving retention, newest-first pagination, profile-root path allowance, and redaction of credential URLs, `cb_` license values, cookie/session tokens, and unrelated absolute paths.
- [ ] Run `python -m pytest tests/manager/test_runtime_logs.py -q`; expect failures because the model/service do not exist.
- [ ] Add `ProfileLogEntry` with indexed `(profile_id, created_at)`, level/event/message bounds, migration upgrade/downgrade, one regex-driven sanitizer, and delete rows older than the newest 2,000 after insert.
- [ ] Run the test again; expect all tests to pass.
- [ ] Commit with `git commit -m "feat(manager): persist sanitized profile runtime logs"`.

### Task 2: Wire logs and expose paginated API

**Files:**
- Modify: `manager_backend/features/runtime/manager.py`
- Modify: `manager_backend/features/runtime/reconcile.py`
- Modify: `manager_backend/features/profiles/routes.py`
- Modify: `manager_backend/features/profiles/schemas.py`
- Test: `tests/manager/test_runtime_api.py`

**Interfaces:**
- Consumes: `append_profile_log` and `list_profile_logs` from Task 1.
- Produces: `GET /api/v1/profiles/{profile_id}/logs` returning `Page[ProfileLogRead]`.

- [ ] Add failing API tests for start, ready, stop, exit/crash, preflight failure, and reconciliation entries; assert no secret appears in response JSON.
- [ ] Run the focused tests and confirm the expected 404 route failure.
- [ ] Add `ProfileLogRead`, route pagination, and runtime hook calls. Use stable events `runtime.start_requested`, `runtime.preflight_failed`, `runtime.process_started`, `runtime.ready`, `runtime.stop_requested`, `runtime.exited`, `runtime.crashed`, and `runtime.reconciled`.
- [ ] Run runtime log/API tests and confirm green.
- [ ] Commit with `git commit -m "feat(manager): expose profile runtime logs"`.

### Task 3: Real runtime and folder counts

**Files:**
- Modify: `manager_backend/features/app/schemas.py`
- Modify: `manager_backend/features/app/routes.py`
- Modify: `manager_backend/features/catalog/routes.py`
- Modify: `manager_backend/features/catalog/schemas.py`
- Modify: `manager_backend/main.py`
- Test: `tests/manager/test_catalog_api.py`
- Test: `tests/manager/test_runtime_api.py`

**Interfaces:**
- Produces: `count_active_runtimes(session, folder_id=None) -> int`; adds `running_session_count` to bootstrap and runtime snapshot, plus `profile_count`/`running_count` to folders.

- [ ] Write failing tests with stopped, starting, running, stopping, crashed, detached, and deleted profiles.
- [ ] Run focused tests; confirm missing response fields.
- [ ] Implement one SQL count helper used by bootstrap, folders, and snapshot; exclude deleted profiles and stale/non-active states.
- [ ] Run focused tests; confirm exact counts.
- [ ] Commit with `git commit -m "feat(manager): report real runtime counts"`.

### Task 4: Safe profile-directory operations

**Files:**
- Create: `manager_backend/features/profiles/directories.py`
- Modify: `manager_backend/features/profiles/routes.py`
- Modify: `manager_backend/features/profiles/schemas.py`
- Modify: `manager_backend/features/profiles/service.py`
- Test: `tests/manager/test_profile_directories.py`

**Interfaces:**
- Produces: `resolve_profile_directory(settings, profile_id) -> Path`, `open_profile_directory(path, opener=os.startfile) -> None`, `POST /profiles/{id}/open-directory`.

- [ ] Write failing tests for derived path, traversal rejection, directory creation, injected opener, non-Windows rejection, and sanitized OS failure.
- [ ] Run focused tests and verify failures.
- [ ] Implement resolved containment using `Path.resolve()` and `is_relative_to`; never accept a client path. Add `profile_directory` to `ProfileRead` and `{profile_directory}` response to the mutation.
- [ ] Run tests and confirm green.
- [ ] Commit with `git commit -m "feat(manager): add safe profile directory actions"`.

### Task 5: True partial PATCH with optimistic concurrency

**Files:**
- Modify: `manager_backend/features/profiles/schemas.py`
- Modify: `manager_backend/features/profiles/service.py`
- Modify: `manager_backend/features/profiles/routes.py`
- Test: `tests/manager/test_profiles_api.py`
- Test: `tests/manager/test_schemas.py`

**Interfaces:**
- Produces: `ProfilePatch` with optional fields plus required `expected_updated_at`; `update_profile` applies `payload.model_fields_set` only.

- [ ] Write failing tests for empty patch, metadata-only patch, explicit nullable clearing, nested atomic replacement, stale timestamp 409, and fingerprint revision/hash behavior.
- [ ] Run focused tests and verify the full-object schema causes the expected failures.
- [ ] Define patch fields independently rather than inheriting create defaults. Compare canonical UTC timestamps, return `profile_conflict` with current safe profile data, and increment fingerprint revision once only for fingerprint-affecting fields.
- [ ] Run profile/schema tests and confirm green.
- [ ] Commit with `git commit -m "feat(manager): make profile patch partial and conflict safe"`.

### Task 6: Frontend runtime observability wiring

**Files:**
- Modify: `manager/frontend/src/types/api.ts`
- Modify: `manager/frontend/src/types/events.ts`
- Modify: `manager/frontend/src/api/realApi.ts`
- Modify: `manager/frontend/src/mocks/mockApi.ts`
- Modify: `manager/frontend/src/features/profiles/ProfileRowActions.tsx`
- Modify: `manager/frontend/src/features/profiles/ProfileDialogs.tsx`
- Modify: `manager/frontend/src/hooks/useAppData.ts`
- Modify: `manager/frontend/src/i18n/en.ts`
- Modify: `manager/frontend/src/i18n/vi.ts`
- Test: `manager/frontend/src/features/profiles/ProfilesPage.test.tsx`

**Interfaces:**
- Consumes: Tasks 2–5 API contracts.

- [ ] Write failing Vitest cases for log dialog pagination, live count, copy/open path, partial request body, and 409 refresh message.
- [ ] Run `npm test -- --run`; confirm expected failures.
- [ ] Update types/adapters/hooks and UI without overwriting concurrent translation/dialog edits; mock mode remains schema-compatible.
- [ ] Run tests, `npm run typecheck`, and `npm run build`.
- [ ] Commit with `git commit -m "feat(manager-frontend): wire runtime observability"`.

### Task 7: Contract and regression gate

**Files:**
- Modify: `manager_backend/openapi.json`
- Modify: `docs/frontend-backend-contract-questions.md`

- [ ] Regenerate OpenAPI with `python -m manager_backend.export_openapi` and assert no unreviewed drift.
- [ ] Run `python -m pytest tests/manager -q` and all frontend verification commands.
- [ ] Update contract notes to mark logs, counts, directory actions, and partial PATCH implemented.
- [ ] Commit with `git commit -m "docs(manager): publish runtime observability contract"`.
