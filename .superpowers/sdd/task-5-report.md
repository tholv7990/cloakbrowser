# Task 5 Report: True Partial PATCH with Optimistic Concurrency

## Status

Implemented and verified. The profile PATCH endpoint now accepts independently defined partial payloads, requires an `expected_updated_at` concurrency token, preserves omitted values, clears only nullable values on explicit `null`, replaces nested objects atomically, and returns a safe 409 conflict response for stale writers.

## Implementation

- Replaced `ProfilePatch(ProfileCreate)` with an independent strict schema.
- Made `expected_updated_at` the only required PATCH field.
- Kept non-nullable PATCH fields omittable while rejecting explicit `null`.
- Kept nullable relationship and identity-mode values clearable with explicit `null`.
- Removed `fingerprint_seed` from the PATCH schema; regeneration remains action-only.
- Applied only fields present in `payload.model_fields_set`.
- Preserved atomic validation/replacement for `location`, `window`, and `behavior`.
- Canonicalized stored and supplied timestamps to UTC before comparison and normalized profile timestamp output to UTC.
- Added a conditional SQL update guard on the stored timestamp. This holds the write version transactionally so two writers with the same token cannot both commit.
- Returned HTTP 409 `profile_conflict` with the current serialized `ProfileRead` under `error.field_errors.current_profile`.
- Updated `updated_at` only for semantic changes, including tags-only changes; empty and same-value PATCH requests remain unchanged.
- Recomputed fingerprint identity only after fingerprint candidate fields changed. The revision increments exactly once per request only when the canonical fingerprint hash changes.
- Declared the PATCH 409 response in the live FastAPI OpenAPI contract. The checked-in `manager_backend/openapi.json` remains untouched for Task 7 regeneration.

## TDD Evidence

1. Baseline: `python -m pytest tests/manager/test_profiles_api.py tests/manager/test_schemas.py -q`
   - 31 passed.
2. RED after adding Task 5 tests:
   - 12 failed, 35 passed.
   - Failures were the expected missing-token, inherited-full-schema, null-handling, concurrency, and revision failures.
3. Initial GREEN:
   - 47 passed for profile/schema tests.
4. Expanded focused verification including the legacy proxy PATCH contract:
   - 56 passed.
5. Transactional race stress:
   - The two-session race test passed 10 consecutive runs; each run produced exactly one successful writer and one `profile_conflict`.

## Coverage Added

- Required concurrency token and provided-field tracking.
- Empty PATCH behavior.
- Metadata-only PATCH and fingerprint stability.
- Nullable clear versus non-nullable rejection.
- Atomic nested replacement.
- Equivalent timezone-offset timestamp acceptance.
- Stale conflict response and safe current profile payload.
- Multiple fingerprint field changes incrementing revision once.
- Same-value and operational-only behavior changes not incrementing revision.
- OpenAPI schema required/nullable/read-only shape.
- Concurrent writers using separate database sessions.
- Existing proxy-reference PATCH updated to send the concurrency token.

## Verification

- Focused Manager tests: 56 passed, 0 failed.
- Full Manager suite before final audit: 204 passed, 2 skipped, 0 failed.
- Final full Manager suite after all additions: 206 passed, 2 skipped, 0 failed.
- `python -m compileall -q manager_backend`: passed.
- Scoped `git diff --check`: passed.
- The commit hash is recorded in the task handoff.

## Files Changed

- `manager_backend/features/profiles/schemas.py`
- `manager_backend/features/profiles/service.py`
- `manager_backend/features/profiles/routes.py`
- `tests/manager/test_profiles_api.py`
- `tests/manager/test_schemas.py`
- `tests/manager/test_proxy_api.py`
- `.superpowers/sdd/task-5-report.md`

## Concerns / Follow-up

- The Manager suite emits one pre-existing Starlette deprecation warning about `httpx`; it is unrelated to Task 5.
- Two environment/platform-dependent Manager tests remain skipped, as before.
- The checked-in OpenAPI artifact is intentionally deferred to Task 7, per the approved plan; the live app schema already reflects `ProfilePatch` and the 409 response.
- Unrelated pre-existing edits in `.superpowers/sdd/progress.md` and task brief files were preserved and excluded from this task's commit.

## Important Findings Follow-up

### Corrections

- Semantic updates now assign `updated_at = max(canonical_utc(utc_now()), canonical_stored + 1 microsecond)`, so a frozen or backward-moving clock cannot leave the optimistic-concurrency token reusable.
- The conditional profile UPDATE now reserves SQLite's writer/CAS transaction before any folder, workflow-status, tag, or proxy lookup. Reference validation therefore observes state serialized after whichever writer obtained the reservation first.
- SQLite write-upgrade/lock failures at the CAS boundary are rolled back and returned as the existing safe `profile_conflict` response with the current profile.
- Proxy deletion now reserves its write before checking profile assignments. If PATCH already won the reservation, deletion observes the committed assignment and returns typed `proxy_in_use`; if a write-upgrade conflict still occurs, it is mapped to a safe proxy conflict rather than exposing SQLite state.
- Profile changes and tag-association writes are explicitly flushed inside the guarded transaction. Residual foreign-key `IntegrityError` failures are rolled back and mapped to HTTP 422 `invalid_profile_reference` with `references=changed_during_update`; no SQL or database text escapes.
- Omitted/null behavior, atomic nested replacement, fingerprint revision/hash rules, and the safe stale-profile payload remain unchanged.

### Follow-up TDD Evidence

1. RED command targeted the frozen-clock writer race, proxy soft-delete interleaving, tag hard-delete interleaving, and residual association FK failure.
   - 4 failed, 0 passed.
   - Observed failures: both frozen-clock writers committed; a deleted proxy was assigned; tag deletion leaked an SQLAlchemy `IntegrityError`; and the injected FK failure exposed raw database exception details.
2. GREEN after the transaction/timestamp fix:
   - 4 passed, 0 failed.
3. RED inverse-order proxy test:
   - 1 failed, 0 passed.
   - PATCH reserved first, but the delete-side stale in-use count let both operations succeed and left the profile assigned to a soft-deleted proxy.
4. GREEN after reserving the proxy delete transaction before its in-use check:
   - 1 passed, 0 failed.
5. Broader profile/schema/proxy/catalog focused suite:
   - 71 passed, 0 failed.
6. Deterministic race stress:
   - All 5 regression tests passed in 10 consecutive runs (50/50 executions).
7. Full Manager suite after the follow-up implementation:
   - 210 passed, 2 skipped, 0 failed.

### Follow-up Files Changed

- `manager_backend/features/profiles/service.py`
- `manager_backend/features/proxies/service.py`
- `tests/manager/test_profiles_api.py`
- `.superpowers/sdd/task-5-report.md`
