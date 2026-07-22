# Frontend ↔ backend contract notes

The Manager frontend is reconciled against `manager_backend/openapi.json` and
the approved runtime-observability, portability/extensions, and diagnostics
specifications. The real adapter is the source of truth; the mock adapter mirrors
that contract for deterministic UI tests.

## Implemented and wired

- Authenticated owner sessions, CSRF-protected mutations, and logout/lock flows.
- Paginated profiles plus sanitized history and opaque cursor/reset log tails.
- Conflict-safe partial profile PATCH using `expected_updated_at`; omitted fields
  remain unchanged and a stale write asks the owner to refresh and review.
- Real running-session count from bootstrap and authenticated WebSocket runtime
  snapshots.
- Manager-owned profile directory path, copy-path action, and Windows
  `open-directory` action.
- Profile JSON import/export and independent cookie JSON/Netscape import/export.
  Download filenames come from the server's `Content-Disposition` header.
- Extension catalog register/list/enable/disable/refresh/unregister and profile
  assignment hydration/replacement through authenticated
  `GET`/`PUT /profiles/{id}/extensions`.
- Persisted diagnostic history and asynchronous direct Google control, Pixelscan,
  IPhey, Cloudflare, and Google Search runs, including filters, progress,
  cancellation, safe errors, and explicit CAPTCHA user-action wording.
- Authenticated, bounded diagnostic report/screenshot artifact routes. Public
  diagnostic JSON contains only API URLs, never local filesystem paths.

## Closed foundation contract gaps

1. Edit mode hydrates assigned extension IDs before resetting the form; an
   unchanged editor preserves the assignment and an explicit edit replaces it.
2. Diagnostic report and screenshot links target fixed authenticated routes.
   The server revalidates exact run ownership, type, size, and link/reparse
   boundaries at read time.
3. The newest-log view polls an opaque, profile-bound cursor tail and honors a
   backend `reset` after retention or truncation. Page controls still provide
   stable historical browsing.

## Safety constraints

- The frontend never renders proxy passwords, cookie values, license values,
  session/CSRF tokens, raw DOM, or arbitrary exception text.
- Public-site diagnostics are observations, not permanent fingerprint or proxy
  guarantees.
- CAPTCHA detection stops at an explicit owner-action-required result. No solve,
  bypass, or automatic interaction is offered.
