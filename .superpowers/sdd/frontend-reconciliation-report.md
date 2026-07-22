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

## Implemented frontend behavior

- Runtime counts reconcile bootstrap data and authenticated WebSocket snapshots.
- Profile logs use real pagination and poll the newest page while the dialog is
  open.
- Profile folder actions use the actual manager-owned directory and backend
  Windows open action.
- Inline and editor changes send only changed profile fields plus
  `expected_updated_at`; conflicts invalidate cached data and request review.
- Profile and cookie downloads preserve the filename supplied by the backend.
- Profile imports surface safe per-item warnings.
- Extension catalog supports register, enable/disable, refresh, unregister, and
  deliberate profile assignment.
- Diagnostics support direct control and Pixelscan/IPHey/Cloudflare/Google
  profile observations, history filters, queued/running progress, cancellation,
  timestamps, safe artifacts, and explicit no-CAPTCHA-automation messaging.

## Contract gaps retained as safe fallbacks

- No read endpoint for a profile's current extension assignments: edit mode
  preserves unknown assignments and warns instead of overwriting them.
- No authenticated diagnostic artifact open/download endpoint: paths are
  display/copy-only.
- No cursor/reset log API: the UI polls paginated page 1 rather than inventing a
  tail contract.

Detailed notes are in `docs/frontend-backend-contract-questions.md`.

## Verification

- `npm test`: 43 passed.
- `npm run typecheck`: passed.
- `npm run build`: passed (Vite emitted the existing large-chunk advisory).
- `npm run format` completed and all scoped files are formatted. A whole-tree
  `format:check` passes immediately after that rewrite, but a clean Windows
  worktree still reports the 91 pre-existing CRLF-formatted frontend files; the
  unrelated line-ending-only rewrite was intentionally not committed.
- Relevant backend profile/runtime/portability/cookie/extension/diagnostic tests:
  197 passed, 2 skipped.
- `git diff --check`: run against the scoped commit before handoff.
