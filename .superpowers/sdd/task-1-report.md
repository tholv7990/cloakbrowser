# Task 1 report: safe profile runtime logs

## Current implementation

- `manager_backend/models.py` defines `ProfileLogEntry`, including its `(profile_id, created_at)` index and bounded database fields.
- `manager_backend/migrations/versions/0008_runtime_observability.py` creates and drops the log table and index.
- `manager_backend/features/runtime/logs.py` accepts only code-owned event templates and bounded structured fields. It derives paths from trusted `ManagerSettings`, validates canonical UUID profile IDs before path use or persistence, and retains exactly the newest 2,000 entries per profile.
- `tests/manager/test_runtime_logs.py` covers templates, structured-path containment, retention, pagination, free-form rejection, canonical IDs, and page-size limits.
- `docs/superpowers/plans/2026-07-22-manager-runtime-observability.md` and `.superpowers/sdd/task-1-brief.md` document the `fields, settings` interface and trusted-root boundary.

## Current security boundary

- `append_profile_log` has no `message` parameter. It supports only the eight approved runtime events: `runtime.start_requested`, `runtime.preflight_failed`, `runtime.process_started`, `runtime.ready`, `runtime.stop_requested`, `runtime.exited`, `runtime.crashed`, and `runtime.reconciled`.
- Messages are generated from code-owned templates. `profile_path` is accepted only for `runtime.process_started`, and can render only the derived profile root or its `user-data` directory; any other value becomes `[REDACTED_PATH]`. `exit_code` is accepted only for `runtime.exited` and only from `-1` through `255`.
- Profile IDs must be lowercase, hyphenated canonical UUIDs. The resolved `<data_root>/profiles/<profile-id>` directory is verified to remain beneath the resolved profiles root.
- Command strings, environment lookups, credentials/tokens, and any arbitrary free-form data have no supported persistence field and are rejected before insertion.

## Superseded implementation history

The original free-message sanitizer and its regex-redaction iterations were superseded by the approved template-only design in commit `d049c32`. Earlier RED/GREEN evidence remains available in the preceding commits; the evidence below applies to the current implementation.

## Current TDD evidence

### RED

Command:

```powershell
python -m pytest tests/manager/test_runtime_logs.py -q
```

Observed exit code: `1`.

```text
1 failed, 14 passed, 1 warning in 7.36s
sqlalchemy.exc.IntegrityError: FOREIGN KEY constraint failed
```

The new traversal/noncanonical-ID regression demonstrated that the prior service constructed a path and attempted insertion for `..\\..\\outside` instead of rejecting the ID before either operation.

### GREEN

Command:

```powershell
python -m pytest tests/manager/test_runtime_logs.py -q
```

Observed exit code: `0`.

```text
15 passed, 1 warning in 7.02s
```

Full regression command:

```powershell
python -m pytest tests/manager -q
```

Observed exit code: `0`.

```text
162 passed, 1 skipped, 1 warning in 28.50s
```

## Concerns

None. The test environment reports FastAPI/TestClient's existing Starlette deprecation warning for `httpx`.
