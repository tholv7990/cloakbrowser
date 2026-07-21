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

## Review fixes

### Security changes

- `append_profile_log` now accepts trusted `ManagerSettings` and derives the sole allowed directory from `settings.data_root / "profiles" / profile_id`; no caller can supply an alternate profile root.
- Events must be lowercase, dotted stable identifiers (`runtime.ready`, `runtime.crashed`, and so on), with a maximum of 80 characters. Invalid events are rejected before persistence.
- The single compiled message sanitizer now redacts generic credential assignments (`password`, `api_key`, secrets, credentials), URL credentials, licenses, cookie/session tokens, complete process-environment representations (`environment`, `env`, and `os.environ`), labelled and unlabelled command lines, and paths outside the derived profile directory.
- Tests now cover invalid events, generic credentials, environment representations, labelled and relative command lines, untrusted-root and UNC paths, and `page_size=201` rejection.

### RED

Command:

```powershell
python -m pytest tests/manager/test_runtime_logs.py -q
```

Observed exit code: `1`.

```text
7 failed, 1 passed, 1 warning in 0.50s
TypeError: append_profile_log() got an unexpected keyword argument 'settings'
```

The tests switched to the trusted settings boundary before the service implemented it. Subsequent focused RED runs also demonstrated the missing relative-command protection and Python-style process-environment protection:

```text
1 failed, 8 passed, 1 warning in 6.15s
AssertionError: 'browser.exe' is contained here: browser.exe [REDACTED_COMMAND]

1 failed, 8 passed, 1 warning in 6.53s
assert '[REDACTED_COMMAND]' in ...

1 failed, 9 passed, 1 warning in 6.39s
AssertionError: assert '\\\\untrusted-server\\profiles\\secret\\Preferences' not in ...
```

### GREEN

Command:

```powershell
python -m pytest tests/manager/test_runtime_logs.py -q
```

Observed exit code: `0`.

```text
10 passed, 1 warning in 15.25s
```

Full regression command:

```powershell
python -m pytest tests/manager -q
```

Observed exit code: `0`.

```text
157 passed, 1 skipped, 1 warning in 24.61s
```

The single warning remains FastAPI/TestClient's existing Starlette deprecation warning for `httpx`.

## Security-first template correction

### Design change

- The Task 1 plan now documents `settings` as the trusted path authority; no interface accepts a caller-provided profile root.
- `append_profile_log` no longer accepts a message argument. It persists only one of eight code-owned templates: `runtime.start_requested`, `runtime.preflight_failed`, `runtime.process_started`, `runtime.ready`, `runtime.stop_requested`, `runtime.exited`, `runtime.crashed`, or `runtime.reconciled`.
- The only structured fields are `profile_path` for `runtime.process_started`, restricted to the manager-derived profile root or its `user-data` directory (all other paths render as `[REDACTED_PATH]`), and `exit_code` for `runtime.exited`, restricted to integers from `-1` through `255`.
- Unknown events, fields, and any positional/free-form message input are rejected before an entry is added to the session.

### RED

Command:

```powershell
python -m pytest tests/manager/test_runtime_logs.py -q
```

Observed exit code: `1`.

```text
13 failed, 1 passed, 1 warning in 0.77s
TypeError: append_profile_log() got an unexpected keyword argument 'fields'
```

The old service still accepted a positional message and did not expose the template/field API. The RED tests covered the full allowed-event set, untrusted structured paths, unsupported events, `cmd /c`, `python -m`, `pwsh -Command`, `os.environ["SECRET"]`, `os.getenv("SECRET")`, Authorization Bearer, refresh tokens, arbitrary message fields, and a direct positional free-form message.

### GREEN

Command:

```powershell
python -m pytest tests/manager/test_runtime_logs.py -q
```

Observed exit code: `0`.

```text
14 passed, 1 warning in 5.94s
```

Full regression command:

```powershell
python -m pytest tests/manager -q
```

Observed exit code: `0`.

```text
161 passed, 1 skipped, 1 warning in 22.26s
```

The warning remains the existing FastAPI/TestClient deprecation warning for `httpx`.
