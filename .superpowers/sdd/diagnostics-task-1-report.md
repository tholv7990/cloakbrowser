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
