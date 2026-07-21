# Manager Runtime Observability and Safe Profile Updates

## Scope

Complete runtime observability for the local Windows Manager and replace full-object profile updates with safe partial updates. This milestone adds sanitized profile logs, real running-session counts, manager-owned profile-directory actions, and optimistic concurrency. AI management is explicitly out of scope.

## Runtime summary

`GET /api/v1/app/bootstrap` adds `running_session_count`. The value is computed from owned `runtime_sessions` whose state is `starting`, `running`, or `stopping`; stale process records are reconciled before they are counted. Folder reads expose `profile_count` and `running_count` using the same state definition.

The WebSocket `runtime.snapshot` remains the realtime source. Its payload adds `running_session_count` so the header can update without polling.

## Profile logs

Create `profile_log_entries` with UUID `id`, `profile_id`, UTC `created_at`, `level`, `event`, and sanitized `message`. Supported levels are `debug`, `info`, `warning`, and `error`. Runtime start, preflight failure, process launch, ready, stop request, process exit, crash, and reconciliation append entries.

`GET /api/v1/profiles/{id}/logs?page=1&page_size=50` returns the standard paginated envelope, newest first. Page size is limited to 200. Retain the newest 2,000 rows per profile and delete older rows after insertion. Messages pass through one sanitizer that removes URLs containing credentials, proxy usernames/passwords, license-shaped values, session/cookie tokens, and absolute paths outside the profile's manager-owned directory. The API never returns command lines or process environments.

## Profile directory

Every profile directory is derived by the backend as `<data_root>/profiles/<profile-id>`; clients never submit paths. `ProfileRead` adds `profile_directory` as a display-safe absolute path. `POST /api/v1/profiles/{id}/open-directory` creates the directory if absent and opens it with Windows Explorer. It rejects non-Windows hosts and any resolved path that escapes the configured root. The frontend copies the returned path locally and calls the endpoint only for “Open folder.”

## Partial PATCH and concurrency

`PATCH /api/v1/profiles/{id}` accepts `ProfilePatch`, whose fields are optional and use Pydantic's provided-field tracking. Omitted fields remain unchanged; explicit `null` clears only nullable fields. Nested `location`, `window`, and `behavior` objects are atomic replacements when provided. Empty patches return the unchanged profile.

The request includes required `expected_updated_at`. If it does not equal the stored timestamp, return HTTP 409 with code `profile_conflict` and the current safe profile representation. This prevents two editors from silently overwriting each other.

Fingerprint seed and revision are unchanged for metadata, folder, tags, status, notes, startup URLs, and proxy assignment. When a fingerprint-affecting field changes, recompute the config hash and increment the revision exactly once. Existing create/duplicate/regenerate behavior is unchanged.

## Errors and security

Missing profiles return 404. Invalid state transitions return 409. Explorer failures return `directory_open_failed` without raw operating-system text. Authentication, Origin, and CSRF rules match all existing mutations.

## Frontend

The header and folders render real counts. Row actions display paginated logs and expose copy/open folder. Inline editors send only changed fields plus `expected_updated_at`; a conflict toast requests refresh instead of retrying automatically.

## Verification

Tests cover log retention and sanitization, runtime count reconciliation, folder counts, root-containment, Windows open behavior, omitted-versus-null PATCH semantics, stale update conflicts, fingerprint revision rules, OpenAPI, WebSocket snapshots, frontend API mapping, and conflict UI.
