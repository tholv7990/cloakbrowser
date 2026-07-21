# Task 3: Real runtime and folder counts

## Scope

Added one SQL-backed `count_active_runtimes(session, folder_id=None)` definition for the observability state set: `starting`, `running`, and `stopping`. It joins profiles, excludes trashed profiles, and is used by bootstrap, folder reads, and WebSocket runtime snapshots. Folder reads also report non-trashed `profile_count`.

## RED

Added failing API coverage for stopped, starting, running, stopping, crashed, detached, and deleted-running profiles.

Command:

```powershell
python -m pytest tests/manager/test_catalog_api.py tests/manager/test_runtime_api.py -q
```

Observed result: `3 failed, 16 passed`. Each failure was the expected missing response field:

- folders: missing `profile_count`;
- bootstrap: missing `running_session_count`;
- `runtime.snapshot`: missing `running_session_count`.

## GREEN

Implemented `count_active_runtimes` in `manager_backend.features.runtime.service`. It performs a SQL count over `RuntimeSession` joined to `Profile`, filtering to `starting`/`running`/`stopping` and `Profile.deleted_at IS NULL`; optional `folder_id` scopes the same definition for folder counts.

- Bootstrap injects the request session and returns `running_session_count`.
- Folder serialization returns `profile_count` and `running_count` for list, create, update, and reorder responses.
- Runtime snapshots return `running_session_count`; the count is also included in the snapshot change marker so a count-only change emits an update.
- Updated the existing backend contract expectation for the expanded bootstrap response.

Focused verification:

```powershell
python -m pytest tests/manager/test_catalog_api.py tests/manager/test_runtime_api.py -q
```

Result: `19 passed, 1 warning` (an existing Starlette TestClient deprecation warning).

Full Manager verification:

```powershell
python -m pytest tests/manager -q
```

First run found one outdated bootstrap-shape assertion in `tests/manager/test_contract.py`. After updating that contract expectation, a fresh run reported: `170 passed, 1 skipped, 1 warning`.

## Self-review

- The only active-count definition is `count_active_runtimes`; all three required consumers call it.
- `queued`, `detached`, `stopped`, and `crashed` are excluded; trashed profiles are excluded from both running and profile counts.
- Startup reconciliation remains responsible for converting stale runtime records before requests/snapshots observe their counts; detached records are not counted.
- No frontend files or logging APIs were changed.
- Scoped diff whitespace checking found no issue in task-owned source/test files. Pre-existing changes to the task briefs and progress file were preserved and left unstaged.

## Concerns

No implementation blockers. The Manager suite retains the pre-existing Starlette TestClient deprecation warning.
