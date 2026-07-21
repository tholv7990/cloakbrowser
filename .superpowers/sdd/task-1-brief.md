### Task 1: Persist safe profile runtime logs

**Files:**
- Modify: `manager_backend/models.py`
- Create: `manager_backend/migrations/versions/0008_runtime_observability.py`
- Create: `manager_backend/features/runtime/logs.py`
- Test: `tests/manager/test_runtime_logs.py`

**Interfaces:**
- Produces: `append_profile_log(session, profile_id, level, event, *, fields, settings) -> ProfileLogEntry` and `list_profile_logs(...) -> Page`.
- `settings` is the trusted path authority. The service derives every profile directory from `settings.data_root / "profiles" / profile_id` and never accepts a caller-provided root.

**Required behavior:**
- Accept only canonical UUID profile IDs before using the ID in a path or database entry. The resolved per-profile directory must remain contained by the resolved manager profiles root.
- Persist only code-owned templates for `runtime.start_requested`, `runtime.preflight_failed`, `runtime.process_started`, `runtime.ready`, `runtime.stop_requested`, `runtime.exited`, `runtime.crashed`, and `runtime.reconciled`.
- Do not accept a free-form message parameter. Reject unknown events and unsupported fields before insertion.
- Support only bounded structured fields: `profile_path` for `runtime.process_started` (the manager-owned profile root or `user-data`; other paths render as `[REDACTED_PATH]`) and `exit_code` for `runtime.exited` (`-1` through `255`).
- Retain exactly the newest 2,000 entries for each profile. List entries newest first with page sizes from 1 through 200.
- Keep `ProfileLogEntry` indexed by `(profile_id, created_at)` and retain the migration upgrade/downgrade.

**Verification:**
- Write failing tests for exact retention, newest-first pagination, trusted-root containment, canonical profile IDs, allowlisted templates, unsafe/free-form rejection, and page-size limits.
- Run `python -m pytest tests/manager/test_runtime_logs.py -q` for RED and GREEN evidence.
- Run `python -m pytest tests/manager -q` before committing.
