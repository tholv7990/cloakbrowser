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

## Independent Review Correction Pass

The independent review identified two Important ownership races. Both were reproduced with new RED regressions and corrected.

- `DiagnosticRunner` now exposes an explicit per-run UUID cleanup lease. The executor registers the lease before the runner starts and the runner settles it only after temporary profiles, profile locks, and the concurrency slot have been released safely.
- Cancellation waits a bounded 250 ms cleanup grace. If a non-cooperative adapter remains alive, the persisted result is `failed` / `cleanup_failed`, not `cancelled`; the runner lease and an executor cleanup observer remain visible until the adapter exits and all resources are released.
- `task_count` is now an ownership-unit count: active workers, deferred-result tasks, cleanup observers, and runner leases are all included. It cannot report zero while the runner retains a temporary profile, profile lock, semaphore slot, or pending persistence transition.
- Shutdown uses a separate bounded two-second policy. It awaits finite cleanup and persistence work. If ownership remains after that bound, shutdown raises a safe `RuntimeError`, retains observable ownership, and still shuts down the unrelated runtime/proxy managers and database engine before surfacing the error.
- Real SQLite write contention no longer causes an active row to be abandoned. `diagnostic_conflict` is re-read: terminal rows are observed, while queued/running rows retain their worker and retry the CAS until the write succeeds. Shutdown additionally refuses to clear any task whose row remains active.
- Added stubborn-adapter regressions covering the cancel response, direct temporary directory, real profile lock, single concurrency slot, eventual release, successful lifespan waiting, and bounded shutdown failure surfacing.
- Added real `BEGIN IMMEDIATE`/20 ms busy-timeout regressions for queued-to-running and running-to-terminal contention. Both assert the row remains active and ownership remains nonzero during contention, then reaches exactly one terminal result after lock release.

Correction RED:

```text
python -m pytest tests/manager/test_diagnostic_async.py -q -k "stubborn or sqlite_write_contention"
2 behavior failures, 2 test-harness path errors

# Behavior failure reproduced before implementation
assert cancelled.json()["status"] == "failed"  # got cancelled
```

The SQLite harness initially referenced a nonexistent settings property. After correcting it to the real `<data_root>/manager.db` path and lowering the checked-out connection busy timeout, the reviewer-reported active-row abandonment was exercised by the queued/running ownership assertions. The final form ran ten consecutive repetitions without a lost worker.

Correction verification:

```text
python -m pytest tests/manager/test_diagnostic_async.py tests/manager/test_diagnostics_api.py tests/manager/test_diagnostic_runner.py tests/manager/test_runtime_api.py tests/manager/test_config.py -q
128 passed, 1 warning in 19.78s

# Five repetitions: stubborn cleanup, SQLite contention, cancel/complete races
5 x 6 passed

python -m pytest tests/manager -q
529 passed, 3 skipped, 1 warning in 63.65s

python -m compileall -q manager_backend
exit 0
```
