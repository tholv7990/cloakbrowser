# Fingerprint Diagnostics Task 4 Report

## Status

Complete. Diagnostic execution is now owned by the application lifespan when all local browser, target, and proxy-preflight adapters are explicitly injected. No frontend, public navigation, OpenAPI route schema, or push was performed.

## Delivered

- Added an application-owned `DiagnosticExecutor` that schedules HTTP 202 rows, performs queued to running to one terminal transition, and runs the synchronous `DiagnosticRunner` outside the event loop.
- Added monotonic 0..100 progress persistence. Regressive, duplicate, late, and post-terminal progress updates cannot regress or overwrite a terminal result.
- Added cooperative cancellation using the runner's owned `threading.Event`. The cancel endpoint awaits the worker, browser cleanup, and resource release before returning the persisted terminal row.
- Added lifespan startup/shutdown ownership. Startup orphan recovery happens before scheduling is enabled; shutdown rejects new schedules, signals every active run, awaits owned worker/deferred tasks, and leaves no executor tasks behind.
- Added explicit deferred-cleanup binding to `DiagnosticRunner`. Deferred cleanup callbacks carry the run UUID, can win the active-to-failed race safely, and amend only that exact run to `cleanup_failed`.
- Added a bounded in-process event broker and authenticated WebSocket delivery for `diagnostic.progress` and `diagnostic.completed`.
- Diagnostic event payloads expose only `id`, `profile_id`, `kind`, `status`, bounded `progress`, and the sanitized terminal `error_code`. They never expose URLs, titles, findings, HTML, cookies, credentials, proxy data, or exceptions.
- Preserved the existing no-adapter lifecycle behavior for persistence/API tests. Partial adapter injection is rejected; deterministic tests inject all adapters together and never navigate publicly.

## TDD Evidence

Initial RED:

```text
python -m pytest tests/manager/test_diagnostic_async.py -q
4 failed
TypeError: create_app() got an unexpected keyword argument 'diagnostic_browser_adapter'
```

Deferred-correlation race RED:

```text
python -m pytest tests/manager/test_diagnostic_async.py::test_deferred_cleanup_amends_only_the_explicit_run_uuid -q
1 failed
assert 'passed' == 'failed'
```

The second RED reproduced a real ordering race where deferred cleanup could report before the ordinary terminal result was stored. The UUID-scoped cleanup CAS now accepts an active row, wins the terminal race as `cleanup_failed`, and causes the ordinary worker result to observe rather than overwrite it.

Final focused GREEN:

```text
python -m pytest tests/manager/test_diagnostic_async.py tests/manager/test_diagnostics_api.py tests/manager/test_diagnostic_runner.py tests/manager/test_runtime_api.py -q
120 passed, 1 warning in 20.14s
```

The new suite includes 20 deterministic cancel/complete races per run and checks exact terminal persistence, cleanup, no task leak, explicit deferred UUID correlation across concurrent same-kind direct controls, scheduler shutdown behavior, authenticated/CSRF-protected mutations, bounded safe WebSocket envelopes, and lifespan cancellation.

## Stress and Full Verification

```text
# Five focused repetitions (100 cancel/complete race cases total)
5 x 7 passed

python -m pytest tests/manager -q
523 passed, 3 skipped, 1 warning in 63.37s

python -m compileall -q manager_backend
exit 0

git diff --check -- <scoped Task 4 paths>
exit 0
```

The sole warning is the pre-existing Starlette `TestClient`/`httpx` deprecation warning.

## Scope and Follow-up

- App construction intentionally requires all three diagnostic adapters together. The deterministic test adapters are local and injected; this task adds no public-site navigator.
- Target normalization remains in Task 3. Real browser/target adapter assembly and opt-in live checks remain a later diagnostics task.
- No frontend files, generated OpenAPI contract, AI functionality, or repository remotes were changed.
