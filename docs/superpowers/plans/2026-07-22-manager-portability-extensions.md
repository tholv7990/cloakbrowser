# Manager Portability and Extensions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add secret-free profile import/export, controlled cookie transfer, and validated unpacked-extension management.

**Architecture:** Dedicated portability and extensions feature packages own parsing/validation. Cookie operations use an injected short-lived browser-context adapter. Extension metadata is persisted separately and launch consumes enabled assignments.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy/Alembic, CloakBrowser Playwright wrapper, React/TypeScript.

## Global Constraints

- Profile documents: version 1, maximum 2 MiB, transactional import.
- Cookie inputs: maximum 10 MiB and 10,000 cookies; stopped profiles only.
- No proxy credentials, cookie values in errors/logs, license/session data, runtime state, or arbitrary paths in profile exports.
- Only existing local unpacked Manifest V2/V3 extensions; no CRX or remote downloads.

---

### Task 1: Versioned profile export/import

**Files:**
- Create: `manager_backend/features/portability/schemas.py`
- Create: `manager_backend/features/portability/profiles.py`
- Create: `manager_backend/features/portability/routes.py`
- Modify: `manager_backend/api.py`
- Test: `tests/manager/test_profile_portability.py`

**Interfaces:**
- Produces: `export_profile(session, id) -> ProfileExportV1`; `import_profile(session, settings, document) -> ProfileImportResult`.

- [ ] Write failing tests for deterministic schema, secret/path/ID exclusion, 2 MiB limit, bad version, catalog resolution, collision naming, fresh UUID/seed, warnings, and rollback.
- [ ] Run the focused test and confirm import symbols/routes are missing.
- [ ] Implement strict Pydantic export/import models, `Content-Disposition` download, and one transaction. Proxy metadata generates a warning and no assignment.
- [ ] Require explicit format/version, omit `chrome-extension://` machine IDs, bound portable permissions and safe validation errors, and require trusted Manager settings.
- [ ] Reserve the SQLite writer transaction before indexed deterministic catalog/name resolution; map lock/integrity failures to safe typed errors.
- [ ] Run focused tests and confirm green.
- [ ] Commit with `git commit -m "feat(manager): add profile import and export"`.

### Task 2: Cookie parsers and normalization

**Files:**
- Create: `manager_backend/features/portability/cookies.py`
- Test: `tests/manager/test_cookie_formats.py`

**Interfaces:**
- Produces: `parse_cookie_payload(data, format) -> CookieParseResult`; `to_netscape(cookies) -> str`.

- [ ] Write failing table tests for manager JSON, Playwright JSON, Netscape, SameSite mapping, expiry, domain/path/name validation, size/count bounds, and value-free warnings.
- [ ] Run focused tests and confirm missing implementation.
- [ ] Implement bounded parsers returning normalized Playwright cookie dictionaries and indexed safe warnings.
- [ ] Run focused tests and confirm green.
- [ ] Commit with `git commit -m "feat(manager): parse portable cookie formats"`.

### Task 3: Controlled cookie browser operations

**Files:**
- Create: `manager_backend/features/portability/browser_cookies.py`
- Modify: `manager_backend/features/portability/routes.py`
- Test: `tests/manager/test_cookie_api.py`

**Interfaces:**
- Produces: `CookieContextAdapter.import_cookies(profile, cookies)` and `.export_cookies(profile)`; cookie endpoints from the spec.

- [ ] Write failing tests with an injected fake adapter for stopped-state enforcement, import counts, export formats, response headers, and context cleanup after failure.
- [ ] Run tests and verify route/service absence.
- [ ] Implement a short-lived headless persistent context using the normal profile launch configuration, `add_cookies`/`cookies`, and `finally` close. Wire multipart/JSON limits before parsing.
- [ ] Run focused tests and confirm green.
- [ ] Commit with `git commit -m "feat(manager): add controlled cookie transfer"`.

### Task 4: Extension persistence and validation

**Files:**
- Modify: `manager_backend/models.py`
- Create: `manager_backend/migrations/versions/0009_extensions.py`
- Create: `manager_backend/features/extensions/schemas.py`
- Create: `manager_backend/features/extensions/service.py`
- Create: `manager_backend/features/extensions/routes.py`
- Modify: `manager_backend/api.py`
- Test: `tests/manager/test_extensions_api.py`

**Interfaces:**
- Produces: extension CRUD/refresh endpoints and `set_profile_extensions(session, profile_id, ids)`.

- [ ] Write failing tests for MV2/MV3 manifests, malformed/oversized JSON, system/temp/network/profile-root rejection, symlink/junction escape, dedupe/hash conflict, enable/refresh/unregister, and assignment.
- [ ] Run focused tests and confirm failure.
- [ ] Add models/migration, strict safe schemas, canonical path validation, bounded permission summaries, stable SHA-256 manifest hash, and metadata-only deletion.
- [ ] Run focused tests and confirm green.
- [ ] Commit with `git commit -m "feat(manager): manage unpacked extensions"`.

### Task 5: Load assigned extensions at runtime

**Files:**
- Modify: `manager_backend/features/runtime/launch.py`
- Modify: `manager_backend/features/runtime/manager.py`
- Test: `tests/manager/test_runtime_manager.py`

**Interfaces:**
- Consumes: enabled assigned extension paths from Task 4.

- [ ] Write a failing launch-builder test asserting only enabled assigned paths are passed through the wrapper's supported extension option and paths are never concatenated into an unsafe shell command.
- [ ] Run the focused test and confirm extension data is ignored.
- [ ] Query assignments at start and pass normalized path list through the launch adapter.
- [ ] Run focused runtime tests and confirm green.
- [ ] Commit with `git commit -m "feat(manager): load profile extensions"`.

### Task 6: Frontend portability and Extensions page

**Files:**
- Modify: `manager/frontend/src/types/api.ts`
- Modify: `manager/frontend/src/api/realApi.ts`
- Modify: `manager/frontend/src/mocks/mockApi.ts`
- Modify: `manager/frontend/src/features/profiles/ProfileDialogs.tsx`
- Create: `manager/frontend/src/features/extensions/ExtensionsPage.tsx`
- Modify: `manager/frontend/src/features/profile-editor/steps.tsx`
- Modify: `manager/frontend/src/app/router.tsx`
- Modify: `manager/frontend/src/i18n/en.ts`
- Modify: `manager/frontend/src/i18n/vi.ts`
- Test: `manager/frontend/src/features/extensions/ExtensionsPage.test.tsx`

- [ ] Write failing UI tests for profile download/upload, cookie format operations, extension register/refresh/enable/unregister, assignment, and uncommon-extension warning.
- [ ] Run Vitest and confirm failures.
- [ ] Implement adapters and accessible UI; use browser Blob downloads and never render cookie values after upload.
- [ ] Run frontend tests, typecheck, and build.
- [ ] Commit with `git commit -m "feat(manager-frontend): add portability and extensions"`.

### Task 7: Contract gate

**Files:**
- Modify: `manager_backend/openapi.json`
- Modify: `docs/frontend-backend-contract-questions.md`

- [ ] Regenerate OpenAPI; run all Manager backend/frontend tests and build.
- [ ] Update contract notes and commit with `git commit -m "docs(manager): publish portability contract"`.
