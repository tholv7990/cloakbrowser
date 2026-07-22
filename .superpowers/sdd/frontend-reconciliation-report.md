# Frontend reconciliation report

## Scope

Reconciled Claude Code's existing Manager UI with the canonical backend APIs for
runtime observability, profile/cookie portability, extension management, and
fingerprint diagnostics. Backend code and schemas were not changed.

## TDD evidence

The initial focused tests failed for missing partial PATCH mapping, paginated
logs, canonical extension/diagnostic routes, server-provided download filenames,
runtime WebSocket frames, extension management UI, diagnostic target controls,
and CAPTCHA-safe wording. Implementation proceeded only after that RED checkpoint.

Added tests cover:

- real adapter request/response contracts;
- backend runtime/diagnostic WebSocket frame normalization;
- extension catalog rendering and local-directory registration;
- all diagnostic targets, observation history, and CAPTCHA user-action copy.
- diff-only profile updates and explicit conflict reconciliation;
- newest-session runtime snapshot deduplication and folder-count invalidation;
- extension mutation retry and partial-success profile/assignment persistence;
- paginated logs, bounded diagnostic findings, import-format parity, and the
  generated static OpenAPI contract gate.

## Implemented frontend behavior

- Runtime counts reconcile bootstrap data and authenticated WebSocket snapshots.
- Profile logs use real pagination and poll the newest page while the dialog is
  open.
- Profile folder actions use the actual manager-owned directory and backend
  Windows open action.
- Inline and editor changes send only changed profile fields plus
  `expected_updated_at`; conflicts invalidate list/detail caches and explicitly
  ask the owner to review the refreshed profile.
- Profile and cookie downloads preserve the filename supplied by the backend.
- Profile imports surface safe per-item warnings.
- Extension catalog supports register, enable/disable, refresh, unregister, and
  deliberate profile assignment. Failed mutations stay visible and retryable;
  assignment failures retry without duplicating the saved profile.
- Diagnostics support direct control and Pixelscan/IPHey/Cloudflare/Google
  profile observations, history filters, queued/running progress, cancellation,
  timestamps, bounded labeled findings, accessible progress, pagination, safe
  artifacts, and explicit no-CAPTCHA-automation messaging.
- Runtime snapshots retain only the newest session for each profile and refresh
  profile/folder counts after runtime transitions.
- The mock adapter now enforces the canonical profile import envelope and UUID
  extension references, matching the real contract more closely.
- `manager_backend/openapi.json` is generated from the running app and guarded
  by a deterministic no-drift test.

## Contract gaps retained as safe fallbacks

- No read endpoint for a profile's current extension assignments: edit mode
  preserves unknown assignments and warns instead of overwriting them.
- No authenticated diagnostic artifact open/download endpoint: paths are
  display/copy-only.
- No cursor/reset log API: the UI polls paginated page 1 rather than inventing a
  tail contract.

Detailed notes are in `docs/frontend-backend-contract-questions.md`.

## Verification

- `npm test`: 57 passed.
- `npm run typecheck`: passed.
- `npm run build`: passed (Vite emitted the existing large-chunk advisory).
- Scoped Prettier formatting completed for every changed frontend file; unrelated
  whole-tree line-ending rewrites were intentionally excluded.
- Relevant backend profile/runtime/portability/cookie/extension/diagnostic tests:
  202 passed, 2 skipped.
- Static OpenAPI no-drift test: passed after deterministic regeneration.
- `git diff --check`: run against the scoped commit before handoff.
