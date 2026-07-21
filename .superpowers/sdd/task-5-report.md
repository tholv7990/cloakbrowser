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
