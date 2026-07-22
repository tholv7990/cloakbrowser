# Manager Profile Portability, Cookies, and Extensions

## Scope

Add versioned profile import/export, safe cookie import/export, and local unpacked-extension management for the Windows single-user Manager. Remote extension downloads, Chrome Web Store installation, packed CRX ingestion, browser-data archive export, and secrets export are out of scope.

## Profile export format

`GET /api/v1/profiles/{id}/export` returns a downloadable UTF-8 JSON document:

```json
{
  "format": "cloakbrowser-manager-profile",
  "version": 1,
  "exported_at": "2026-07-22T00:00:00Z",
  "profile": {},
  "extensions": []
}
```

The profile contains editable configuration, tags by name/color, workflow status by name/color, and extension references by manifest metadata. It excludes IDs, timestamps, runtime state, filesystem paths, proxy credentials, cookies, browser data, diagnostic data, and license/session material. Proxy assignment exports only non-secret scheme/host/port metadata and is not automatically recreated on import.

Portable startup URLs exclude `chrome-extension://` URLs because their extension IDs are machine-specific. Extension portability uses manifest metadata only. Import requires trusted Manager settings so profile-directory creation cannot be skipped.

`POST /api/v1/profiles/import` accepts one document up to 2 MiB. It requires explicit format/version fields, validates all fields strictly, creates a new UUID, fingerprint seed, revision, and profile directory, resolves or creates catalog values by normalized name, and reports warnings for skipped proxy assignment, machine-specific startup URLs, or missing extensions. Name collisions gain ` (imported N)` deterministically. Import reserves the SQLite writer transaction before resolution and commits transactionally, preventing concurrent imports from duplicating normalized catalog values or collision names.

## Cookies

Cookie import accepts a multipart file or JSON request up to 10 MiB with explicit format `json`, `playwright`, or `netscape`. Validation limits the import to 10,000 cookies and checks domain, path, name, value size, expiry, SameSite, Secure, and HttpOnly fields. The response reports imported, skipped, and rejected counts plus bounded field-safe warnings.

Cookie operations require runtime state `stopped`. They launch a short-lived, headless CloakBrowser persistent context for the profile, call Playwright context cookie APIs, then close it in `finally`. They do not read or decrypt Chromium's SQLite cookie database directly. Export returns Playwright-compatible JSON by default and supports Netscape text. Values are returned only in the explicit authenticated download response and never logged or stored in manager tables.

Endpoints:

- `POST /api/v1/profiles/{id}/cookies/import`
- `GET /api/v1/profiles/{id}/cookies/export?format=playwright|netscape`

## Extensions

Create `extensions` with UUID, normalized absolute directory, manifest name/version/description, manifest version, permissions summary, enabled flag, timestamps, and a stable manifest hash. Create `profile_extensions` with composite `(profile_id, extension_id)`.

`POST /api/v1/extensions` registers an existing unpacked directory. The backend resolves the path, requires a regular `manifest.json`, validates Manifest V2 or V3 JSON, rejects symlinks/junction escapes, and rejects paths under profile data, temporary directories, Windows system directories, or network shares. It never copies or executes extension code during registration. Duplicate normalized paths return the existing record when the manifest hash matches and 409 when metadata changed until refreshed.

Endpoints:

- `GET /api/v1/extensions`
- `POST /api/v1/extensions`
- `GET /api/v1/extensions/{id}`
- `PATCH /api/v1/extensions/{id}` for enabled state and refresh
- `DELETE /api/v1/extensions/{id}` to unregister metadata only
- `PUT /api/v1/profiles/{id}/extensions` with the complete assigned ID list

Profile launch passes enabled assigned directories through CloakBrowser's supported extension-loading interface. The frontend warns that identical uncommon extensions can correlate profiles. An extension disabled globally is omitted without deleting assignments.

## Errors and security

All paths are backend-resolved and validated. API responses never echo arbitrary manifest content or extension source. Import parser errors contain field paths, not file contents. Cookie values are omitted from errors. Mutations require authenticated session, allowed Origin, and CSRF.

## Frontend

Profiles actions provide profile export/import and cookie import/export. The Extensions page lists registered unpacked extensions, supports register/refresh/enable/unregister, and the profile wizard assigns registered extensions. Downloads use browser blobs and preserve server-provided filenames.

## Verification

Tests cover deterministic export, secret exclusion, import transaction rollback, format/version/size limits, name collision handling, all cookie formats, stopped-state enforcement, context cleanup on failure, manifest validation, path containment, assignment, runtime launch arguments, OpenAPI, frontend flows, and mock compatibility.
