# Task 2: Runtime observability report

## Scope

Implemented authenticated, paginated profile runtime logs and wired the
required stable events without weakening the existing trusted log boundary.

Changed files:

- `manager_backend/features/profiles/routes.py`
- `manager_backend/features/profiles/schemas.py`
- `manager_backend/features/runtime/manager.py`
- `manager_backend/features/runtime/worker.py`
- `manager_backend/features/runtime/reconcile.py`
- `tests/manager/test_runtime_api.py`

`worker.py` was added to the task's listed files because it owns the launch,
ready, normal-exit, and crash transitions that must emit the required events.

## TDD evidence

### RED: missing logs endpoint

Command:

```powershell
python -m pytest tests/manager/test_runtime_api.py::test_runtime_preflight_and_crash_logs_do_not_expose_secrets -q
```

Output (exit code 1):

```text
E       assert 404 == 200
E        +  where 404 = <Response [404 Not Found]>.status_code
1 failed, 1 warning in 0.61s
```

This confirmed the new API test failed for the intended reason: the profile
logs route did not exist.

### GREEN: focused runtime observability tests

Command:

```powershell
python -m pytest tests/manager/test_runtime_logs.py tests/manager/test_runtime_api.py tests/manager/test_runtime_manager.py tests/manager/test_runtime_reconcile.py -q
```

Output (exit code 0):

```text
36 passed, 1 warning in 9.44s
```

The warning is FastAPI/TestClient's third-party deprecation notice for the
installed `httpx` version; no Manager test emitted an application warning.

## Final verification

Command:

```powershell
python -m pytest tests/manager -q
```

Output (exit code 0):

```text
166 passed, 1 skipped, 1 warning in 46.80s
```

## Self-review

- The read endpoint is under the existing authenticated API router, verifies
  that the profile exists, returns the standard page envelope newest-first,
  defaults to page 1 / 50 rows, and rejects page sizes over 200.
- `ProfileLogRead` is strict and exposes only the persisted safe fields:
  ID, profile ID, UTC timestamp, level, stable event name, and sanitized
  message.
- `RuntimeManager` records start and stop requests. `ProfileWorker` records
  process start, ready, normal exit, preflight failure, and crash. Runtime
  reconciliation records `runtime.reconciled` for each resolved active
  runtime and `runtime.crashed` for a missing owned process.
- All writes continue through `append_profile_log` with the trusted
  `ManagerSettings`, fixed event names, and allowlisted structured fields;
  no raw exception, command line, proxy, or environment value is logged.
- API tests cover lifecycle, preflight failure, crash, reconciliation,
  authentication, pagination bounds, and confirm the synthetic proxy secret
  is absent from returned JSON.
- `git diff --check` found no whitespace issue in Task 2 files. It reports a
  pre-existing blank line at EOF in the user-modified
  `.superpowers/sdd/task-2-brief.md`, which was not changed.

## Concerns

None for the implementation. Run Manager tests as `python -m pytest`; the
standalone `pytest` command in this environment initially loaded a different
runtime import state, while the explicit interpreter command consistently
used this worktree and produced the verification above.
