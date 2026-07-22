# Frontend ↔ backend contract notes

The Manager frontend is reconciled against `manager_backend/openapi.json` and
the approved runtime-observability, portability/extensions, and diagnostics
specifications. The real adapter is the source of truth; the mock adapter mirrors
that contract for deterministic UI tests.

## Implemented and wired

- Authenticated owner sessions, CSRF-protected mutations, and logout/lock flows.
- Paginated profiles and sanitized profile logs.
- Conflict-safe partial profile PATCH using `expected_updated_at`; omitted fields
  remain unchanged and a stale write asks the owner to refresh and review.
- Real running-session count from bootstrap and authenticated WebSocket runtime
  snapshots.
- Manager-owned profile directory path, copy-path action, and Windows
  `open-directory` action.
- Profile JSON import/export and independent cookie JSON/Netscape import/export.
  Download filenames come from the server's `Content-Disposition` header.
- Extension catalog register/list/enable/disable/refresh/unregister and profile
  assignment through `PUT /profiles/{id}/extensions`.
- Persisted diagnostic history and asynchronous direct Google control, Pixelscan,
  IPhey, Cloudflare, and Google Search runs, including filters, progress,
  cancellation, safe errors, and explicit CAPTCHA user-action wording.

## Remaining contract gaps and safe frontend fallbacks

1. **Read profile extension assignments.** The backend exposes
   `PUT /profiles/{id}/extensions`, but no corresponding GET endpoint or
   `extension_ids` on `ProfileRead`. Therefore edit mode cannot hydrate the
   current assignments. The frontend preserves them when the extension step is
   untouched, shows an explanatory warning, and only sends PUT when the owner
   deliberately selects assignments. Clearing all assignments from edit mode is
   deferred until the backend exposes the current list.
2. **Open or download diagnostic artifacts.** Diagnostic responses expose
   root-contained `screenshot_path` and `report_path`, but there is no
   authenticated route to open/download those artifacts. The frontend displays
   and copies the safe path and clearly notes the limitation; it does not create
   an unauthenticated static-file URL.
3. **Cursor/tail profile logs.** The backend provides page/page-size pagination,
   not cursor/reset/tail semantics. The log dialog polls the newest page while
   open and labels that behavior. It does not invent cursor behavior.

## Safety constraints

- The frontend never renders proxy passwords, cookie values, license values,
  session/CSRF tokens, raw DOM, or arbitrary exception text.
- Public-site diagnostics are observations, not permanent fingerprint or proxy
  guarantees.
- CAPTCHA detection stops at an explicit owner-action-required result. No solve,
  bypass, or automatic interaction is offered.
