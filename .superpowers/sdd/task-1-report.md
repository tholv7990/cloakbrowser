# Task 1 report: persisted and sanitized profile logs

## Files changed

- `manager_backend/models.py`: adds `ProfileLogEntry` with a profile/created-at index, bounded fields, and an allowed-level check.
- `manager_backend/migrations/versions/0008_runtime_observability.py`: creates and drops `profile_log_entries` and its index.
- `manager_backend/features/runtime/logs.py`: provides append/list services, a single regex-driven sanitizer, newest-2,000 retention, and pagination limited to 200 entries.
- `tests/manager/test_runtime_logs.py`: covers retention, newest-first pagination, manager-owned path allowance, and credential/license/token/path redaction.

## TDD evidence

### RED

Command:

```powershell
python -m pytest tests/manager/test_runtime_logs.py -q
```

Observed exit code: `1`.

Observed failure:

```text
ModuleNotFoundError: No module named 'manager_backend.features.runtime.logs'
```

The new test module could not import the requested service because the module and ORM model did not yet exist.

### GREEN

Command:

```powershell
python -m pytest tests/manager/test_runtime_logs.py -q
```

Observed exit code: `0`.

```text
4 passed, 1 warning in 6.27s
```

The warning is FastAPI/TestClient's existing Starlette deprecation warning for `httpx`.

## Additional verification

```powershell
python -m py_compile manager_backend/models.py manager_backend/features/runtime/logs.py manager_backend/migrations/versions/0008_runtime_observability.py
python -m pytest tests/manager -q
```

Both exited `0`; manager tests reported:

```text
151 passed, 1 skipped, 1 warning in 23.73s
```

Migration upgrade/downgrade/upgrade was verified against a dedicated temporary SQLite data root:

```powershell
python -m alembic -c manager_backend/alembic.ini upgrade head
python -m alembic -c manager_backend/alembic.ini downgrade 0007_proxy_quality_runs
python -m alembic -c manager_backend/alembic.ini upgrade head
```

All three commands exited `0`; Alembic ran revision `0008_runtime_observability` in both upgrade passes and downgraded it successfully.

## Self-review

- Sanitization uses one compiled regex with named alternatives and never emits credentials, `cb_` values, session/cookie token values, or paths outside `<profile_root>/<profile_id>`.
- Retention deletes only entries beyond the deterministic newest-first 2,000 selection for the current profile.
- The paginated result is ordered by `created_at DESC, id DESC`, matching retention's ordering and making ties deterministic.
- Migration names, field types, check constraint, index, foreign-key cascade, upgrade, and downgrade match the ORM model.

## Concerns

None. The suite still reports the pre-existing FastAPI/TestClient deprecation warning noted above.
