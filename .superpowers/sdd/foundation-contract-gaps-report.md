# Foundation contract gaps implementation report

Base: `c962eb1`

## Delivered

- Authenticated profile extension assignment GET with deterministic name/UUID ordering; edit mode hydrates before form reset.
- Authenticated diagnostic report and screenshot routes with exact run/kind ownership, bounded regular-file reads, link/reparse and swap checks, safe content headers, and no public filesystem paths.
- Opaque HMAC profile-log tail cursors with bounded chronological batches and deterministic reset on malformed, cross-profile, retained-away, or truncated positions; historical page controls remain available.
- Real/mock adapters, frontend types, UI wiring, static OpenAPI, and contract notes updated together.

## Verification

- Backend: `python -m pytest tests/manager -q` — 548 passed, 3 skipped.
- Frontend: `npm test -- --run` — 66 passed.
- TypeScript: `npm run typecheck` — passed.
- Production frontend: `npm run build` — passed (existing bundle-size advisory only).
- OpenAPI: export plus `tests/manager/test_openapi_static.py` — passed.
- Python compile: `python -m compileall -q manager_backend tests/manager` — passed.
- Diff whitespace check: `git diff --check` — passed for scoped product files.

No secrets, raw diagnostic paths, cookie values, proxy credentials, or CAPTCHA automation were added.

## Independent-review hardening follow-up

- Diagnostic artifact reads now hold Windows directory handles for both the
  diagnostics root and the individual run root, compare stable volume/file
  identities and final paths, and revalidate both boundaries before and after
  the bounded file read. Deterministic replacement tests cover each boundary.
- Profile logs now allocate an atomic, persistent, per-profile monotonic
  sequence. Migration `0011_profile_log_sequence` deterministically backfills
  existing rows, initializes counters, enforces uniqueness, and has an
  exercised downgrade. Tail cursors remain opaque HMAC values and do not expose
  the sequence.
- Report and screenshot success responses explicitly advertise
  `application/json` and `image/png`; every error response remains the canonical
  JSON envelope.
- The frontend clears a tail cursor synchronously when the profile or requested
  limit changes, preventing one request from using the prior profile's cursor.
- POSIX artifact files are opened by name relative to the held run-directory
  descriptor with no-follow and nonblocking flags. Windows denies run-directory
  rename/delete while serving and reads through a native file handle whose
  identity, final path, type, and size are verified before and after reading.
- Log-tail merging preserves the backend's monotonic sequence order while still
  deduplicating and applying the visible history limit; timestamps and UUIDs no
  longer reorder newly delivered entries.
