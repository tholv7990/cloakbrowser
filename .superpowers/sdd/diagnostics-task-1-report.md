# Fingerprint Diagnostics Task 1 Report

## Status

Complete. Diagnostic persistence and the authenticated API lifecycle are implemented without a runner, public navigation, frontend work, or push.

## Delivered

- Added `DiagnosticRun` persistence for the five approved kinds and six approved statuses.
- Added Alembic revision `0010_diagnostics` with kind/status/progress checks, `ON DELETE SET NULL` profile history, a requested-time index, and a partial unique index enforcing one queued/running run per profile.
- Added strict request/response/page schemas and authenticated list, detail, create, and cancel routes.
- Creation returns HTTP 202 and uses server-owned HTTPS target mappings. Clients cannot supply target URLs or result content.
- Added status-transition validation, progress clamping to 0-100, terminal timestamps, cancellation, and safe stable errors.
- Added an injected scheduling callback with a default no-op, so Task 1 never launches a browser or visits a public target.
- Added startup recovery that marks orphaned queued/running rows failed with the stable `manager_restarted` code and fixed safe copy.
- Suppressed artifact paths unless they resolve below the exact manager-owned diagnostic run directory.
- Preserved the existing API-wide session, exact-origin, and CSRF enforcement.

## TDD Evidence

Initial RED:

```text
python -m pytest tests/manager/test_diagnostics_api.py -q
12 failed
```

Failures were the expected missing manager state, routes, model/module, and migration.

Final focused GREEN:

```text
python -m pytest tests/manager/test_diagnostics_api.py -q
12 passed, 1 warning in 2.96s
```

Final full Manager suite:

```text
python -m pytest tests/manager -q
373 passed, 3 skipped, 1 warning in 48.01s
```

Additional verification:

```text
python -m compileall -q manager_backend
exit 0
```

The focused suite includes Alembic upgrade-to-head and downgrade-to-`0009_extensions` verification.

## Safety and Scope

- No page HTML, cookies, credentials, browser storage, response bodies, or arbitrary exception text are accepted by or returned from these routes.
- No worker/runner, realtime events, frontend changes, generated OpenAPI update, or public-site navigation is included; those remain assigned to later tasks.
- The only warning is the pre-existing Starlette `TestClient`/`httpx` deprecation warning.

## Review Correction Pass

All Task 1 review findings were corrected in a follow-up TDD pass.

- Lifecycle transitions, cancellation, result completion, and progress now use SQL compare-and-swap predicates. Terminal races have one winner; stale terminal/progress writers receive stable `diagnostic_not_active` or `diagnostic_conflict` errors.
- Progress CAS compares both the expected active status and prior progress value.
- Creation obtains `BEGIN IMMEDIATE` before profile and active-run checks. Soft-delete, hard-delete, and concurrent-create races are serialized at a clear SQLite write boundary.
- SQLite extended/base constraint codes are inspected without stringifying private database details. Foreign-key/profile races map to `profile_not_found`; the partial unique active-profile conflict maps to `diagnostic_already_active`.
- Scheduler exceptions are caught after persistence and atomically map active rows to `failed` with `scheduler_unavailable` and fixed public copy. A concurrent cancellation is preserved and the profile slot is released for retry.
- `DiagnosticResultUpdate` is a strict internal result boundary with per-kind keys, scalar-only closed finding values, bounded paths, closed error codes, and status/error consistency checks.
- Target URLs are enforced by a kind-to-target database check and are always serialized from the server allowlist.
- Summary and error copy are fixed templates. Legacy arbitrary findings, summaries, codes, messages, and out-of-root paths serialize as bounded safe values; contained paths remain available.

Review RED evidence:

```text
python -m pytest tests/manager/test_diagnostics_api.py -q -k "terminal_winner or progress_cannot or concurrent_create or delete_wins or scheduler or typed_result or migration"
28 failed, 1 passed, 11 deselected

python -m pytest tests/manager/test_diagnostics_api.py::test_concurrent_progress_updates_compare_the_expected_progress_version -q
1 failed
```

Final review verification:

```text
python -m pytest tests/manager/test_diagnostics_api.py -q
42 passed, 1 warning in 5.23s

python -m pytest tests/manager/test_diagnostics_api.py::test_diagnostic_migration_upgrade_and_downgrade -q
1 passed, 1 warning in 0.27s

# Five repetitions of 20 terminal races plus progress/terminal and create races
5 x 22 passed (110 stress cases)

python -m pytest tests/manager -q
403 passed, 3 skipped, 1 warning in 50.30s
```

The warning remains the pre-existing Starlette `TestClient`/`httpx` deprecation warning. No frontend, public navigation, or push was added.
