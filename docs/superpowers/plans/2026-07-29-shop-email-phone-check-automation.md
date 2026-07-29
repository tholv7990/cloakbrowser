# Shop Email Phone-OTP Check Automation — Implementation Plan

> Execute test-first in small commits. Do not change CloakBrowser engine code. Do not make
> real Shop requests in unit/integration tests.

**Design:** `docs/superpowers/specs/2026-07-29-shop-email-phone-check-automation-design.md`

## Phase 1 — Persistence and strict contract

### Task 1: Add failing model and migration tests

**Files**

- Add: `tests/manager/test_shop_check_migration.py`
- Add: `tests/manager/test_shop_check_models.py`
- Modify: `manager_backend/models.py`
- Add: next migration under `manager_backend/migrations/versions/`

Test fresh and upgraded databases, constraints, indexes, cascade behavior, and schema drift.
Add `ShopCheckRun`, `ShopCheckEmail`, and `ShopCheckWorker`. Store email references and
SHA-256 fingerprints, never plaintext emails or proxy secrets.

Run:

```powershell
pytest tests/manager/test_shop_check_migration.py tests/manager/test_shop_check_models.py -q
```

### Task 2: Define strict schemas and route skeleton

**Files**

- Add: `manager_backend/features/shop_check/__init__.py`
- Add: `manager_backend/features/shop_check/schemas.py`
- Add: `manager_backend/features/shop_check/routes.py`
- Modify: backend API router registration file
- Add: `tests/manager/test_shop_check_api.py`

Add strict create/read/list/export/cleanup schemas and authenticated `/api/v1` routes.
Create payload email text must be write-only and bounded. Verify extra fields are rejected,
operation IDs are unique, and responses contain no secrets.

## Phase 2 — Input, classification, and phone metadata

### Task 3: Parse and secure authorized email input

**Files**

- Add: `manager_backend/features/shop_check/input.py`
- Modify: `manager_backend/features/shop_check/service.py`
- Add: `tests/manager/test_shop_check_input.py`

Normalize, validate, deduplicate, preserve input order, calculate worker count, store full
emails in `CredentialStore`, and compensate credential writes on transaction failure.
Never log raw input.

### Task 4: Build deterministic Shop page classifier

**Files**

- Add: `manager_backend/features/shop_check/classifier.py`
- Add: `manager_backend/features/shop_check/fixtures/*.html`
- Add: `tests/manager/test_shop_check_classifier.py`

Implement semantic signals for all terminal outcomes in English and Vietnamese. Require
multiple signals for phone OTP. Treat conflicting or changed markup as `unknown`.

### Task 5: Add calling-code parser

**Files**

- Add: `manager_backend/features/shop_check/phone.py`
- Add: `tests/manager/test_shop_check_phone.py`
- Modify dependency manifest only if a maintained offline calling-code package is selected

Return exact, ambiguous, or unknown mappings. Special-case shared numbering plans through
data, not guesses. Never use proxy geography to fill phone geography.

## Phase 3 — Worker orchestration

### Task 6: Isolate the browser interaction adapter

**Files**

- Add: `manager_backend/features/shop_check/browser.py`
- Add: `tests/manager/test_shop_check_browser.py`

Define a protocol for launch, navigation, semantic querying, filling, clicking, clearing
Shop origin state, screenshot capture, and stop. Implement against the existing runtime/CDP
control surface. Tests use a fake adapter.

### Task 7: Create profiles and 711 routes transactionally

**Files**

- Add: `manager_backend/features/shop_check/provisioner.py`
- Modify only shared proxy/profile services where a narrowly reusable primitive is missing
- Add: `tests/manager/test_shop_check_provisioner.py`

Group emails by configured size, generate unique 711 sticky routes, preflight with bounded
retries, create unique profiles, assign startup URL, and write immutable run ownership.
Compensate partial failures without deleting unrelated resources.

### Task 8: Implement coordinator and recovery

**Files**

- Add: `manager_backend/features/shop_check/coordinator.py`
- Add: `tests/manager/test_shop_check_coordinator.py`
- Modify app startup/shutdown wiring

Use a bounded executor with one database session per worker. Persist transitions. Recompute
aggregates from rows. Implement cancellation, retryable requeue, crash recovery, and clean
shutdown. Default 3 parallel workers; enforce server-side maximum.

Required race tests:

- Cancel while a proxy check completes.
- Retry while a stale worker callback returns.
- Two aggregate recomputations overlap.
- Startup recovery runs twice.
- A worker fails after four of five emails.

## Phase 4 — Export and exact-scope cleanup

### Task 9: Add safe exports

**Files**

- Add: `manager_backend/features/shop_check/export.py`
- Add: `tests/manager/test_shop_check_export.py`
- Modify routes/schemas

Generate authoritative CSV and matched-email TXT. Deduplicate, neutralize spreadsheet
formula injection, use atomic writes, and avoid raw email logging.

### Task 10: Add manual cleanup

**Files**

- Add: `manager_backend/features/shop_check/cleanup.py`
- Add: `tests/manager/test_shop_check_cleanup.py`
- Modify routes/schemas

Resolve profile IDs exclusively from immutable run ownership. Stop owned runtimes, enforce
profile-root path containment, delete one owned profile at a time, persist partial progress,
and preserve proxies/results/exports.

Hard-gate tests:

- A manually created profile with the same name/tag survives.
- Another run's profile survives.
- A client cannot inject profile IDs or paths.
- An active owned runtime is stopped before deletion.
- A filesystem failure leaves a retryable cleanup result.

## Phase 5 — Frontend

### Task 11: Add typed API contract

**Files**

- Modify: `manager/frontend/src/types/api.ts`
- Modify: `manager/frontend/src/api/types.ts` or active API interface
- Modify: `manager/frontend/src/api/real.ts`
- Modify: `manager/frontend/src/mocks/mockApi.ts`
- Modify: `manager/frontend/src/mocks/data.ts`
- Modify: `manager/frontend/src/api/queryKeys.ts` or active query-key module
- Add/update matching tests

Wire exact backend paths and bodies. Never place provider secrets or unmasked email lists in
query keys, URLs, errors, or telemetry.

### Task 12: Build Shop-check creation wizard

**Files**

- Add: `manager/frontend/src/features/automation/ShopCheckWizard.tsx`
- Add: `manager/frontend/src/features/automation/ShopCheckWizard.test.tsx`
- Modify: `manager/frontend/src/features/automation/AutomationPage.tsx`
- Modify: `manager/frontend/src/features/automation/api.ts`
- Modify: `manager/frontend/src/i18n/en.ts`
- Modify: `manager/frontend/src/i18n/vi.ts`

Show valid/duplicate/invalid counts, computed worker count, five-emails-per-profile warning,
711 configuration, region, concurrency, output choice, and authorization acknowledgement.

### Task 13: Build run progress and completion cleanup UI

**Files**

- Add: `manager/frontend/src/features/automation/ShopCheckRunView.tsx`
- Add: `manager/frontend/src/features/automation/ShopCheckRunView.test.tsx`
- Add: `manager/frontend/src/features/automation/ShopCheckCleanupDialog.tsx`
- Add tests for cleanup dialog
- Modify automation page/hooks/i18n

Show aggregate outcomes, workers, paginated results, filters, retry controls, exports, and a
persistent completion banner. Cleanup confirmation must show exact run-owned profile count
and must call only the run cleanup endpoint.

## Phase 6 — Contract and release gates

### Task 14: Regenerate OpenAPI and run backend gates

```powershell
python -m manager_backend.export_openapi
pytest tests/manager -m "not slow" -q
```

Require no static OpenAPI diff after generation, no secret-leak assertion failures, and no
existing automation/proxy/runtime regression.

### Task 15: Run frontend gates

From `manager/frontend`:

```powershell
npm run typecheck
npm run test
npm run build
```

### Task 16: Authenticated Windows smoke test

Using owned test accounts only:

- Configure 711 credentials without exposing them.
- Run 1–2 local fixture/test emails before any larger authorized run.
- Confirm unique session directives and proxy preflight.
- Confirm five-email grouping and state reset.
- Confirm CSV/TXT output.
- Confirm cleanup deletes only the run-owned temporary profiles.
- Capture sanitized timing and failure evidence.

## Review checkpoints for Codex

Codex reviews after Phases 1, 3, 4, and 6. Each review is a hard gate:

1. Secret and personal-data leakage.
2. Cross-run/manual-profile deletion risk and filesystem containment.
3. Coordinator races, stuck runs, cancellation, and startup recovery.
4. False-positive phone detection and ambiguous calling-code handling.
5. API/frontend contract and OpenAPI parity.
6. Meaningful tests rather than mocked happy-path assertions.

