# Backend contract — Session history (`GET /sessions`)

**Owner:** backend (Codex). Frontend is built (a "Recent sessions" panel on the Resources screen, `features/diagnostics/SessionHistory.tsx`, EN/VI). Read-only.

**Reference:** `Quantum-Source-Clean-*/backend/services/session_history_service.py`.

## Goal

One record per profile **launch** — startup time, duration, and how it ended — so the user can see recent runtime activity. Read-only observability; no mutations.

## Endpoint

```
GET /api/v1/sessions?limit=25   -> 200 RuntimeSessionRecord[]
```

- Auth: same session-cookie + origin check as other routes.
- `limit` optional (default 25), newest-first (`started_at` descending).
- Cheap DB read.

## Response shape

Mirror `RuntimeSessionRecord` in `manager/frontend/src/types/api.ts`:

```jsonc
[
  {
    "id": "sess_...",
    "profile_id": "prof_...",
    "profile_name": "marketplace-us-01",   // joined from the profile at write time or query time
    "started_at": "2026-07-22T09:00:00Z",  // ISO-8601 UTC
    "ended_at": "2026-07-22T09:05:00Z",    // null while still running
    "duration_seconds": 300,               // null while running
    "startup_ms": 690,                     // launch → browser context ready; null if not measured
    "exit_reason": "closed"                // 'closed' | 'stopped' | 'crashed' | 'timeout' | 'unknown' | null
  }
]
```

## Data model (SQLAlchemy + Alembic)

New table `runtime_session_history`:
- `id` (str, pk), `profile_id` (fk → profile, index), `started_at`, `ended_at` (nullable), `duration_seconds` (int, nullable), `startup_ms` (int, nullable), `exit_reason` (str enum, nullable).
- `profile_name` is not stored — join to the profile (or snapshot the name at write time if you want history to survive profile deletion; snapshotting is simpler for the frontend).

## Implementation

- We already have the runtime layer (`features/runtime/` — `RuntimeSession`, `ProfileWorker`, `manager.py`, `reconcile.py`). Write a history row when a runtime reaches a **terminal** state:
  - On `start`: record `started_at` and measure `startup_ms` as the wall time from launch invocation to the `BrowserContext` being ready (the `ProfileWorker`/`launcher` already owns both points).
  - On `stop`/`crashed`/reconcile-detected exit: set `ended_at = now`, `duration_seconds`, and map the terminal state to `exit_reason` (`stopped` for user stop, `crashed` for unexpected exit, `timeout` if a launch/stop timed out, `closed` if the browser window was closed by the user, else `unknown`).
- Add the row from the same place that transitions `RuntimeSession.state` to terminal (e.g. in `ProfileWorker` finalization) so history and live state stay consistent.
- Optionally cap retention (e.g. keep the latest N per profile or globally) — not required for v1.

## Tests

`tests/manager/test_sessions_api.py`: launching+stopping a mocked runtime writes exactly one history row with a non-null `duration_seconds` and the right `exit_reason`; `GET /sessions?limit=n` returns newest-first and respects the limit. Update `openapi.json` if checked in.
