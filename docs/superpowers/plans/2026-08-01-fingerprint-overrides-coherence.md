# Fingerprint Overrides and Coherence Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional explicit fingerprint attribute flags to all three wrapper ports and provide a Windows-persona coherence validator, persistence, launch wiring, and inline Manager feedback without changing default launches.

**Architecture:** Python remains the reference implementation. Each wrapper validates dedicated override inputs and appends normalized native Chromium flags through its existing ordered deduplication builder. Manager stores overrides in additive nullable columns, includes them in identity hashing and launch snapshots, and calls a pure backend validator whose structured findings drive both launch blocking and localized editor feedback.

**Tech Stack:** Python 3.11+, pytest, Playwright, TypeScript/Vitest, .NET/C#/xUnit, FastAPI/Pydantic, SQLAlchemy/Alembic, React/TypeScript, project i18n dictionaries.

## Global Constraints

- Work only from CloakBrowser's repository and documented binary flag surface; do not inspect or reference competitor source.
- Keep Python, TypeScript, and .NET launch-flag behavior identical.
- All seven overrides are optional; omitted values must preserve the exact existing argument list and order.
- Masking remains native to the patched binary; add no JavaScript injection.
- Manager remains a Windows-only fingerprint persona.
- Screen overrides must never create or change a Playwright/Puppeteer viewport.
- Do not change humanize, timing, or CDP code paths.
- Use a new additive Alembic migration; never edit an existing migration.

---

### Task 1: Python explicit override API

**Files:**
- Modify: `cloakbrowser/browser.py`
- Test: `tests/test_stealth_unit.py`

**Interfaces:**
- Produces: optional snake-case parameters `gpu_vendor`, `gpu_renderer`, `hardware_concurrency`, `device_memory`, `screen_width`, `screen_height`, and `brand` on all six launch functions and `build_args`.
- Produces: one private normalization helper used only for these dedicated options.

- [ ] **Step 1: Write failing baseline and override-order tests**

Add tests that capture `build_args(True, [], headless=True)` before overrides, assert the same call with seven `None` values is identical, and assert a seeded input plus all seven values yields exactly one of each expected flag with every override index greater than the `--fingerprint` index. Add a raw duplicate such as `--fingerprint-gpu-vendor=old` and expect only the dedicated normalized value.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `pytest tests/test_stealth_unit.py -k fingerprint_override -q`

Expected: FAIL because `build_args` and launch entry points do not accept the new keywords.

- [ ] **Step 3: Write failing validation and viewport-isolation tests**

Parametrize empty/whitespace strings, booleans, zero/negative integers, values over 1024 for hardware/RAM, and screen values outside 320–16384. Assert `ValueError`. Assert valid screen overrides emit only `--fingerprint-screen-*` and never add `--window-size` or a viewport-related flag.

- [ ] **Step 4: Implement centralized validation and ordered override insertion**

Add helpers with signatures equivalent to:

```python
def _normalize_fingerprint_string(name: str, value: str | None) -> str | None: ...
def _normalize_fingerprint_int(
    name: str, value: int | None, *, minimum: int, maximum: int
) -> int | None: ...
def _append_fingerprint_override(seen: dict[str, str], key: str, value: object) -> None:
    seen.pop(key, None)
    seen[key] = f"{key}={value}"
```

Extend `build_args` and all callers. Dedicated overrides are applied after timezone/locale and before extensions/window management. Do not alter any viewport calculation.

- [ ] **Step 5: Run Python focused tests**

Run: `pytest tests/test_stealth_unit.py -k fingerprint_override -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```text
git add cloakbrowser/browser.py tests/test_stealth_unit.py
git commit -m "feat(python): add explicit fingerprint overrides"
```

### Task 2: TypeScript explicit override API

**Files:**
- Modify: `js/src/types.ts`
- Modify: `js/src/args.ts`
- Test: `js/tests/stealth.test.ts`
- Test: `js/tests/stealth.puppeteer.test.ts`

**Interfaces:**
- Consumes: Task 1 names and validation limits.
- Produces: camel-case fields on `LaunchOptions`; `buildArgs(options)` remains the single Playwright/Puppeteer assembly path.

- [ ] **Step 1: Add failing parity tests**

Use the same seed, raw duplicate, values, and expected flag list as Python. Assert omitted fields preserve the existing array byte-for-byte and screen fields add no viewport/window flag.

- [ ] **Step 2: Run focused Vitest tests and verify failure**

Run: `cd js && npm run test -- --run tests/stealth.test.ts tests/stealth.puppeteer.test.ts`

Expected: FAIL on missing option properties/flags.

- [ ] **Step 3: Add failing invalid-value tests**

Cover empty strings, fractional/boolean/non-finite numbers, bounds, and paired valid values. Expect `Error` messages naming the invalid field.

- [ ] **Step 4: Implement TypeScript options and normalization**

Add documented optional fields to `LaunchOptions`. In `args.ts`, implement typed string/integer normalization and a helper that calls `seen.delete(key)` before `seen.set(key, flag)`, preserving the same priority and limits as Python.

- [ ] **Step 5: Run TypeScript checks**

Run: `cd js && npm run typecheck && npm run test -- --run tests/stealth.test.ts tests/stealth.puppeteer.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit**

```text
git add js/src/types.ts js/src/args.ts js/tests/stealth.test.ts js/tests/stealth.puppeteer.test.ts
git commit -m "feat(js): add explicit fingerprint overrides"
```

### Task 3: .NET explicit override API and three-port parity

**Files:**
- Modify: `dotnet/src/CloakBrowser/LaunchOptions.cs`
- Modify: `dotnet/src/CloakBrowser/CloakLauncher.cs`
- Test: `dotnet/tests/CloakBrowser.Tests/BuildArgsTests.cs`
- Create: `tests/fixtures/fingerprint_override_parity.json`
- Modify: Python, JS, and .NET test files from Tasks 1–2 to consume or mirror the fixture.

**Interfaces:**
- Consumes: Tasks 1–2 names, limits, ordering, and expected fixture.
- Produces: nullable Pascal-case properties and optional `BuildArgs` parameters.

- [ ] **Step 1: Create the shared parity fixture and failing .NET tests**

The fixture contains one seed-bearing raw-args input, all seven normalized values, and the exact seven expected override flags in order. Add omitted, duplicate, invalid, and no-viewport assertions.

- [ ] **Step 2: Run focused .NET tests and verify failure**

Run: `cd dotnet && dotnet test CloakBrowser.sln --filter FingerprintOverride`

Expected: FAIL because `LaunchOptions`/`BuildArgs` lack the properties.

- [ ] **Step 3: Implement .NET validation and move-to-end semantics**

Add nullable properties to `LaunchOptions`. Extend `BuildArgs`; add a dedicated setter that removes a key from both `seen` and `order` before re-adding it. Throw `ArgumentException`/`ArgumentOutOfRangeException` before launch using the same rules as Python/TypeScript.

- [ ] **Step 4: Pass options from both .NET launch paths**

Update plain and persistent/context launch calls to supply every property to `BuildArgs`. Verify copying code that creates derived `LaunchOptions` retains the fields.

- [ ] **Step 5: Run all port parity tests**

Run the three focused test commands from Tasks 1–3 and compare their expected ordered lists to `tests/fixtures/fingerprint_override_parity.json`.

Expected: PASS with identical override sets and order.

- [ ] **Step 6: Commit**

```text
git add dotnet/src dotnet/tests tests/fixtures tests/test_stealth_unit.py js/tests
git commit -m "feat(dotnet): add fingerprint overrides and parity fixture"
```

### Task 4: Manager persistence, schemas, and migration

**Files:**
- Create: `manager_backend/migrations/versions/0020_fingerprint_overrides.py`
- Modify: `manager_backend/models.py`
- Modify: `manager_backend/features/profiles/schemas.py`
- Modify: `manager_backend/features/profiles/service.py`
- Modify: `manager_backend/fingerprints.py`
- Test: `tests/manager/test_fingerprint_override_migration.py`
- Test: `tests/manager/test_schemas.py`
- Test: `tests/manager/test_profiles_api.py`

**Interfaces:**
- Produces: seven nullable columns and API fields; database `browser_brand` maps to API field `brand`.
- Produces: paired Manager screen validation and identity-hash participation.

- [ ] **Step 1: Write the failing migration test**

Upgrade from revision `0019_shop_check_credential_journal` to head and assert all seven columns exist, are nullable, and existing profiles contain null values without changing their seed.

- [ ] **Step 2: Write failing schema/API round-trip tests**

Create and patch profiles with all overrides, read them back, and assert exact values. Cover bounds, blank strings, one-sided screen dimensions, and null defaults.

- [ ] **Step 3: Write failing fingerprint-hash tests**

Assert changing each override changes `fingerprint_config_hash`, while creating an existing-style profile with all null values remains valid and stable.

- [ ] **Step 4: Implement the additive migration and model fields**

Use `down_revision = "0019_shop_check_credential_journal"`. Add nullable strings/integers with the lengths in the design. Downgrade removes only these new columns.

- [ ] **Step 5: Implement schemas and service serialization**

Add one reusable Pydantic validation path for string/range rules and a model validator requiring screen width/height together. Update `_profile_values`, patch handling, `profile_to_dict`, duplication, and every explicit `ProfileCreate` reconstruction.

- [ ] **Step 6: Extend fingerprint identity hashing**

Add an `overrides` mapping to `build_fingerprint_identity`, normalized in a stable key order. Update all call sites and increment the Manager fingerprint revision only if required by existing revision semantics; preserve seeds.

- [ ] **Step 7: Run focused Manager tests**

Run: `pytest tests/manager/test_fingerprint_override_migration.py tests/manager/test_schemas.py tests/manager/test_profiles_api.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```text
git add manager_backend tests/manager/test_fingerprint_override_migration.py tests/manager/test_schemas.py tests/manager/test_profiles_api.py
git commit -m "feat(manager): persist fingerprint overrides"
```

### Task 5: Pure coherence validator and API contract

**Files:**
- Create: `manager_backend/features/profiles/fingerprint_coherence.py`
- Modify: `manager_backend/features/profiles/schemas.py`
- Modify: `manager_backend/features/profiles/routes.py`
- Modify: `manager_backend/features/profiles/service.py`
- Test: `tests/manager/test_fingerprint_coherence.py`
- Test: `tests/manager/test_profiles_api.py`

**Interfaces:**
- Produces: `validate_fingerprint_coherence(profile: Mapping[str, Any]) -> dict[str, Any]`.
- Produces: typed finding/result response models and a draft-validation profile endpoint.

- [ ] **Step 1: Write failing pure-function tests**

Add one test for each rule: non-Windows UA, UA/pinned-major mismatch, NVIDIA/AMD/Intel vendor-renderer mismatch, Direct3D on non-Windows input, Apple/Metal on Windows, timezone/proxy-timezone warning, locale/proxy-country warning, coherent profile, deterministic ordering, and input non-mutation.

- [ ] **Step 2: Run validator tests and verify failure**

Run: `pytest tests/manager/test_fingerprint_coherence.py -q`

Expected: FAIL because the module/function does not exist.

- [ ] **Step 3: Implement normalized rule helpers and validator**

Keep each rule private and independently testable. Use stable codes such as `ua.platform_mismatch`, `ua.version_mismatch`, `gpu.vendor_renderer_mismatch`, `gpu.platform_mismatch`, `geo.timezone_mismatch`, and `geo.locale_mismatch`. Reuse the existing GeoIP country/locale data rather than introducing an eight-country table.

- [ ] **Step 4: Add draft validation endpoint and response schemas**

Add a profiles route that accepts the same identity/location subset used by create/edit and returns typed findings. Do not persist during validation. Ensure messages contain no proxy credentials.

- [ ] **Step 5: Add endpoint tests**

Assert coherent/warning/error response bodies, authentication, strict response shape, and no database mutation.

- [ ] **Step 6: Run focused tests**

Run: `pytest tests/manager/test_fingerprint_coherence.py tests/manager/test_profiles_api.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```text
git add manager_backend/features/profiles tests/manager/test_fingerprint_coherence.py tests/manager/test_profiles_api.py
git commit -m "feat(manager): validate fingerprint coherence"
```

### Task 6: Runtime propagation and launch blocking

**Files:**
- Modify: `manager_backend/features/runtime/launcher.py`
- Modify: `manager_backend/features/runtime/manager.py`
- Test: `tests/manager/test_launcher.py`
- Test: `tests/manager/test_runtime_manager.py`

**Interfaces:**
- Consumes: stored overrides and Task 5 validator.
- Produces: snapshot keys and `persistent_context_kwargs` values matching Python launch keyword names.

- [ ] **Step 1: Write failing snapshot/kwargs tests**

Assert every stored override reaches `profile_launch_snapshot`, then `persistent_context_kwargs`, unchanged. Assert null values are omitted or passed as `None` consistently and existing snapshots remain unchanged in effective behavior.

- [ ] **Step 2: Write failing launch-blocking tests**

Construct an incoherent stored profile and assert runtime preflight fails before `cloakbrowser.launch_persistent_context` is called. Construct warning-only and coherent profiles and assert launch proceeds.

- [ ] **Step 3: Implement propagation and preflight**

Add the seven fields to the canonical snapshot and kwargs. Call the pure validator in runtime preflight, log stable finding codes without secrets, block only `severity == "error"`, and retain warnings for UI/log visibility.

- [ ] **Step 4: Run focused runtime tests**

Run: `pytest tests/manager/test_launcher.py tests/manager/test_runtime_manager.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```text
git add manager_backend/features/runtime tests/manager/test_launcher.py tests/manager/test_runtime_manager.py
git commit -m "feat(manager): enforce fingerprint coherence at launch"
```

### Task 7: Profile editor fields and localized findings

**Files:**
- Modify: `manager/frontend/src/features/profiles/types.ts`
- Modify: `manager/frontend/src/features/profiles/api.ts`
- Modify: `manager/frontend/src/features/profiles/NewProfileModal.tsx`
- Modify: `manager/frontend/src/features/profiles/NewProfileModal.test.tsx`
- Modify: `manager/frontend/src/i18n/en.ts`
- Modify: `manager/frontend/src/i18n/vi.ts`
- Test: relevant i18n parity test discovered in `manager/frontend/src`.

**Interfaces:**
- Consumes: Task 5 validation endpoint/finding codes.
- Produces: optional editor fields, review summary, inline localized findings, and error-based save blocking.

- [ ] **Step 1: Write failing editor tests**

Test empty automatic defaults, all explicit values in create payload, paired screen validation, review display, backend validation request, warning display without blocking, error display with save disabled, and edit-profile hydration.

- [ ] **Step 2: Run focused frontend tests and verify failure**

Run: `cd manager/frontend && npm run test -- --run src/features/profiles/NewProfileModal.test.tsx`

Expected: FAIL because types, fields, and validation UI do not exist.

- [ ] **Step 3: Implement types/API and identity controls**

Add nullable override properties to profile draft/read types and one API function for draft validation. Add a collapsed advanced identity section; normalize empty inputs to null and numeric inputs to integers.

- [ ] **Step 4: Implement findings presentation**

Map stable backend codes to en/vi translation keys. Render field-adjacent findings and an accessible summary. Do not duplicate coherence rules in React. Disable save only when the latest validation result contains an error.

- [ ] **Step 5: Add synchronized translations and parity coverage**

Add labels, hints, statuses, and all finding-code messages to both dictionaries. Run the repository's translation-key parity test.

- [ ] **Step 6: Run frontend tests/build**

Run: `cd manager/frontend && npm run test -- --run src/features/profiles/NewProfileModal.test.tsx && npm run build`

Expected: PASS.

- [ ] **Step 7: Commit**

```text
git add manager/frontend/src/features/profiles manager/frontend/src/i18n
git commit -m "feat(manager-ui): show fingerprint coherence findings"
```

### Task 8: OpenAPI, documentation, and full verification

**Files:**
- Modify: `manager_backend/openapi.json` (generated)
- Modify: `README.md`
- Modify: `js/README.md` if it documents launch options separately
- Modify: `dotnet/README.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: documented public APIs and verified release artifacts.

- [ ] **Step 1: Document optional overrides and defaults**

Add one concise table to each public API document. State that the seed remains the base, explicit values override only named attributes, invalid values fail before launch, and screen flags do not emulate viewport dimensions.

- [ ] **Step 2: Regenerate OpenAPI**

Run: `python -m manager_backend.export_openapi`

Expected: only the new profile fields, validation request/response schemas, and endpoint appear in `manager_backend/openapi.json`.

- [ ] **Step 3: Run root Python gates**

Run: `pytest -m "not slow"`

Run: `pytest tests/manager -m "not slow" -q`

Expected: PASS.

- [ ] **Step 4: Run JavaScript/TypeScript gates**

Run: `cd js && npm run typecheck && npm run test && npm run build`

Expected: PASS.

- [ ] **Step 5: Run .NET gate**

Run: `cd dotnet && dotnet test CloakBrowser.sln`

Expected: PASS.

- [ ] **Step 6: Prove final three-port parity**

Run the shared parity fixture assertions in all three ports and record their identical ordered override lists in the test output or final verification notes.

- [ ] **Step 7: Review generated/static diffs and repository status**

Confirm OpenAPI has no unrelated changes, migrations form one head, no competitor references were added, and pre-existing unrelated files remain untouched.

- [ ] **Step 8: Commit**

```text
git add README.md js/README.md dotnet/README.md manager_backend/openapi.json
git commit -m "docs: document fingerprint overrides and validation"
```
