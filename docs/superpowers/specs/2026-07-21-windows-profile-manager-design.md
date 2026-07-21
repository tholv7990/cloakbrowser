# CloakBrowser Windows Profile Manager Design

## 1. Purpose

Build a local, single-user web dashboard for creating, organizing, launching, and diagnosing isolated CloakBrowser profiles on Windows.

The product should feel operationally similar to the dense profile-management interfaces in GoLogin, Vision, and the supplied HideMyAcc references, while using original CloakBrowser branding and exposing only features supported by this codebase.

This document is the contract between two implementations:

- **Frontend owner:** Claude Code builds the React application and consumes the API/events defined here.
- **Backend owner:** Codex builds FastAPI, SQLite persistence, Windows credential storage, process management, proxy diagnostics, and CloakBrowser integration.

Version 1 is Windows-only, local-only, and single-user. It has one locally authenticated owner account but no cloud synchronization, cloud registration, billing, profile sharing, team permissions, mobile personas, or alternative browser engines.

## 2. Technology decisions

### Frontend

- React 19 with TypeScript.
- Vite for development and production bundling.
- Tailwind CSS for styling.
- TanStack Table for profile/proxy tables.
- TanStack Query for server state and mutations.
- React Hook Form plus Zod for forms and client validation.
- Lucide icons.
- Native WebSocket client for runtime events.
- Vitest and React Testing Library.

### Backend

- Python 3.10+.
- FastAPI and Uvicorn, bound only to `127.0.0.1`.
- Pydantic v2 request/response models.
- SQLAlchemy 2 and Alembic migrations.
- SQLite with WAL mode and foreign keys enabled.
- Python `keyring` with Windows Credential Manager for proxy secrets.
- Existing CloakBrowser Python API for persistent contexts.
- Existing proxy-quality scanner for diagnostics.
- `psutil` for owned-process inspection and cleanup.
- Pytest for unit and integration tests.

### Distribution target

Development starts with:

```powershell
python -m cloakbrowser.manager
```

The backend starts on a loopback port, opens the local dashboard in the default browser, serves the compiled frontend in production, and prints a credential-free local URL. Packaging into a Windows executable is a later milestone.

## 3. Security model

- Listen only on `127.0.0.1`; never bind to LAN interfaces by default.
- First-run setup creates exactly one local owner using an email address and password.
- Normalize and store the email locally; do not verify it or send it to a cloud service.
- Hash passwords with Argon2id. Never store or log plaintext passwords.
- Authenticate the dashboard with an opaque random session in an `HttpOnly`, `SameSite=Strict` cookie. Store only a SHA-256 hash of the session token.
- Require an exact Origin and a session-bound `X-CSRF-Token` for mutating requests.
- Keep sessions across dashboard, app, browser, and Windows restarts until explicit revocation.
- Apply increasing local throttling after five failed logins. Login errors do not reveal whether an email exists.
- Password change requires the current password and revokes every session.
- Logout revokes the current session. Lock revokes every session without stopping running profiles.
- Keep the per-install token as an internal bootstrap secret only. Never expose it to frontend JavaScript or use it as the dashboard login credential.
- Validate `Origin` against the manager's exact loopback origin.
- Use strict JSON content types and explicit CORS denial; no wildcard CORS.
- Store proxy usernames/passwords in Windows Credential Manager. SQLite stores only a credential reference.
- API responses never return a raw password, authentication header, CAPTCHA token, browser cookie value, or complete launch command containing secrets.
- Frontend password fields are write-only. Edit responses return `has_password: true|false`.
- Send authenticated upstream proxy traffic through the credential-safe localhost relay already implemented for proxy-quality checks when the raw URL would otherwise enter Chromium process arguments.
- Do not let callers select arbitrary user-data paths. The backend assigns every profile path below the configured profile root.
- Normalize and validate profile IDs, filenames, extension paths, import paths, and startup URLs.
- Destructive deletion defaults to a recoverable application trash directory.

## 4. Local filesystem layout

Default manager root:

```text
%LOCALAPPDATA%\CloakBrowser\Manager\
├── manager.db
├── install-token
├── logs\
├── profiles\
│   └── <profile-uuid>\
│       ├── user-data\
│       ├── downloads\
│       └── profile.json
├── reports\
│   └── proxy-quality\
└── trash\
```

`profile.json` is a safe recovery manifest containing profile ID, display name, timestamps, fingerprint seed, and non-secret settings. It must not contain proxy credentials or cookies.

## 5. Navigation and screen map

The fixed left sidebar contains:

1. Profiles
2. Folders
3. Proxies
4. Diagnostics
5. Settings

The sidebar may collapse to icons. It does not include advertising, subscriptions, accounts, sharing, synchronization, proxy sales, or a store.

The header contains the page title, running-session count, backend connection state, and light/dark/system theme control.

## 6. Profiles screen

### Layout

- Tabs: All Profiles, Pinned, Recently Used, and folder shortcuts.
- Search input over name, notes, tags, proxy label, and profile ID.
- Filter button with active-filter count.
- Toolbar: Add Profile, Quick Create, Bulk Actions, Import, Export.
- Dense configurable table.
- Footer: result count, rows per page, current page, next/previous controls.

### Default table columns

1. Selection checkbox.
2. Pinned indicator.
3. Name and short profile ID.
4. Browser/Windows persona.
5. Proxy country, masked endpoint, and health indicator.
6. Tags.
7. Notes preview.
8. Last opened.
9. Workflow status.
10. Runtime message.
11. Start/Stop action.
12. Overflow menu.

Columns can be shown, hidden, and reordered in local frontend preferences.

### Runtime states

- `stopped`: Start enabled.
- `starting`: spinner; actions that mutate identity disabled.
- `running`: Stop enabled; display-window action enabled.
- `stopping`: spinner.
- `crashed`: Start enabled; last error visible.
- `unreachable`: backend lost ownership/state; reconciliation required.

The backend is authoritative for runtime state.

### Row overflow actions

**Profile**

- Edit profile
- Pin/unpin
- Add/remove folder
- Duplicate profile
- Change fingerprint

**Data**

- Import cookies
- Export cookies
- Open profile folder
- Export profile configuration

**Proxy and diagnostics**

- Assign/edit proxy
- Test proxy
- View latest proxy-quality report
- Refresh GeoIP alignment

**Runtime**

- Start/stop
- Bring browser window to front
- View runtime logs

**Copy submenu**

- Profile ID
- Profile path
- Masked proxy endpoint
- Fingerprint seed
- Credential-free launch example

**Danger zone**

- Remove from current folder
- Move profile to trash

No Share or Transfer actions exist in version 1.

## 7. Create and edit profile wizard

The wizard uses a left step rail and persistent footer actions: Back, Next, Save, and Save & Run.

### Step 1: General

- Name, required, 1-80 characters.
- Folder, optional.
- Workflow status, optional.
- Tags, zero or more.
- Notes, optional, maximum 4,000 characters.
- Zero or more startup URLs. Supported schemes are `http`, `https`, and explicitly approved `chrome-extension` URLs belonging to an enabled local extension.
- The manager does not capture website usernames, passwords, or 2FA secrets. Login state belongs in the persistent browser profile; the manager is not a password vault.

### Step 2: Proxy and location

- Direct connection or reusable proxy record.
- Inline quick-create proxy option.
- Test-before-every-launch toggle.
- Geo mode: `proxy`, `manual`, or `system`; default to `proxy` when a proxy is assigned.
- Locale and IANA timezone; explicit values override GeoIP.
- WebRTC mode: `proxy`, `direct`, or `disabled`; default to `proxy` with a proxy.
- Geolocation mode: `proxy`, `manual`, `ask`, or `block`; default to `ask`.
- Manual latitude, longitude, and accuracy are accepted only in manual mode.
- Display blocking errors for invalid values and warnings for proxy/location conflicts.

### Step 3: Browser identity

- Platform is fixed to Windows and browser is fixed to CloakBrowser Chromium.
- Browser version mode is `installed` or `pinned`; pinned versions must pass the CloakBrowser numeric version validator.
- Fingerprint preset defaults to `consistent`.
- Stable fingerprint seed is generated once.
- “Generate new fingerprint” explicitly creates a new seed and warns that websites may recognize a new device.
- User-agent mode is `automatic` or `custom`. Manual override is advanced and shows a consistency warning.

The current engine exposes one `windows` fingerprint platform, not distinct Windows 10 and Windows 11 personas. Android, iOS, macOS, Linux, Firefox, Opera, Brave, Edge, Yandex, and WebView are not selectable in version 1.

### Step 4: Window and appearance

- Manager profiles are headed-only in version 1.
- Window mode is `maximized` or `custom`; default to `maximized`.
- Custom window width and height are allowed only in custom mode.
- Color scheme is `system`, `light`, or `dark`.
- Do not independently expose screen resolution and viewport by default. CloakBrowser uses real headed window geometry to keep screen, outer-window, and inner-window dimensions coherent.

### Step 5: Cookies and storage

- Import Netscape, JSON, or Playwright storage state.
- Show import validation summary.
- Store cookies, local storage, cache, and login state inside the profile's dedicated user-data directory, never inside the profile database row.
- Version 1 supports import/export, not a full cell-by-cell cookie editor.

### Step 6: Extensions

- Select zero or more unpacked local extension directories.
- Backend validates extension manifests and stores normalized paths.
- Clearly warn that identical uncommon extensions across profiles may link identities.

### Step 7: Advanced behavior

- Humanization toggle and preset: `default` or `careful`.
- Clear-cache-before-launch toggle, off by default.
- Restore-previous-tabs toggle.
- Download directory mode: `profile` or `custom`.
- Browser permissions with an allowlisted schema.
- Ignore-HTTPS-errors toggle, off by default and visibly warned.
- Hardware concurrency mode: `automatic` or `custom` and a validated custom value.
- GPU mode: `automatic` or `custom_vendor` and an allowlisted compatible vendor.
- Additional Chromium arguments with denylisted unsafe or manager-owned flags.
- Allowing multiple simultaneous instances is not configurable; it is always false.

Do not expose independent controls for Canvas, WebGL image/renderer, AudioContext, ClientRects, fonts, speech voices, media-device IDs, plugins, device name, host LAN IP, MAC address, device memory, or SSL feature disabling. The current engine does not offer tested independent controls for those surfaces. Applicable fingerprint surfaces are derived coherently from the stable seed and binary.

### Step 8: Review

- Display profile summary.
- Display blocking validation errors.
- Display non-blocking fingerprint/proxy consistency warnings.
- Save creates the database record and profile directory transactionally.
- Save & Run launches only after save succeeds.

## 8. Proxy library and editor

Proxies are reusable records that can be assigned to multiple profiles.

### Proxy table

- Label.
- Protocol.
- Masked endpoint.
- Exit IP.
- Country/city.
- Type and confidence.
- Reputation.
- Latency.
- Assigned profile count.
- Last checked.
- Actions: Edit, Quick Test, Full Test, Assign, Delete.

### Proxy editor slide-over

- Mode: Direct, HTTP, HTTPS, SOCKS5, SOCKS5H.
- Paste-and-parse field for common proxy formats.
- Host and port.
- Username and write-only password.
- Test before profile launch toggle.
- Quick Test button.
- Full Quality Test button.
- Save button disabled until required fields validate.

Use SOCKS5H guidance when remote proxy DNS is required. Plain SOCKS5 intentionally reports local DNS delegation.

### Quick test result

- Connectivity.
- Exit IP agreement.
- Median latency.
- Country, city, timezone, ASN, organization.

### Full quality result

- Type and confidence.
- Reputation and matched lists.
- Google outcome.
- Third-party Cloudflare Turnstile demo outcome.
- HTTP/WebRTC/DNS/timezone/locale alignment.
- Screenshot/report links.
- Timestamp and observed-scope disclaimer.

## 9. Folders screen

- Create, rename, reorder, and trash folders.
- Display profile count and running count.
- A profile belongs to zero or one folder in version 1.
- Folder deletion does not delete profiles; profiles become unfiled.
- Bulk move profiles to a folder.

## 10. Diagnostics screen

- Proxy Quality history.
- Pixelscan regression launch shortcut.
- Direct-network Google control shortcut.
- Browser/runtime version information.
- Recent launch failures.
- Links to saved JSON and screenshots.

Diagnostics never automate CAPTCHA interaction.

## 11. Settings screen

- Profile root and report root display; changes require migration confirmation.
- Default profile locale/timezone/persona.
- Default test-before-launch behavior.
- Rows per page.
- Theme.
- Browser binary information and update check.
- Log retention.
- Trash retention.
- Export/import manager settings without secrets.

## 12. Database schema

All IDs are UUID strings. All timestamps are UTC ISO-8601 in APIs and UTC-aware database values.

### `profiles`

- `id` primary key.
- `name`.
- `folder_id` nullable foreign key.
- `status_id` nullable foreign key.
- `notes`.
- `pinned` boolean.
- `startup_urls_json`, validated list of safe URLs.
- Platform is implicit and fixed to `windows`; browser is implicit and fixed to CloakBrowser Chromium. Neither is stored as a user-controlled field.
- `fingerprint_seed` unsigned integer stored as decimal text.
- `fingerprint_preset` enum: `default`, `consistent`.
- `fingerprint_revision` positive integer identifying the manager fingerprint contract.
- `fingerprint_config_hash` SHA-256 of the canonical non-secret fingerprint configuration.
- `browser_version_mode` enum: `installed`, `pinned`.
- `browser_version` nullable numeric version pin.
- `user_agent_mode` enum: `automatic`, `custom`.
- `custom_user_agent` nullable.
- `location_json`, validated exact location schema containing geo, locale, timezone, WebRTC, and geolocation choices.
- `window_json`, validated exact window-mode, dimensions, and color-scheme schema.
- `behavior_json`, validated exact humanization, cache, tabs, downloads, permissions, HTTPS-error, hardware-concurrency, GPU, and additional-argument schema.
- `proxy_id` nullable foreign key.
- `test_proxy_before_launch` boolean.
- `created_at`, `updated_at`, `last_opened_at`.
- `total_runtime_seconds`.
- `deleted_at` nullable.

Profile rows never contain website credentials, 2FA secrets, cookies, local storage, proxy passwords, or raw authorization values.

`fingerprint_seed` is unique across active and trashed profiles. It is generated once
with a cryptographically secure unsigned 64-bit value and remains stable across
launches. Duplicate-profile and regenerate-fingerprint operations create a new seed.
The manager never randomizes a profile fingerprint automatically before launch.

The configuration hash detects accidental duplicate configurations and update drift;
it is not a claim that every browser-exposed surface differs. Runtime diagnostics must
separately verify same-profile stability and cross-profile differences on surfaces
actually controlled by the installed CloakBrowser binary.

### `folders`

- `id`, `name`, `position`, timestamps.

### `tags`

- `id`, `name`, `color`, timestamps.

### `profile_tags`

- Composite primary key `profile_id`, `tag_id`.

### `workflow_statuses`

- `id`, `name`, `color`, `position`.

### `proxies`

- `id`, `label`, `scheme`, `host`, `port`.
- `username_present` boolean.
- `credential_ref` nullable unique reference into Windows Credential Manager.
- `test_before_launch` boolean.
- Safe cached fields: exit IP, location, ASN, type/confidence, reputation, latency, last checked.
- Timestamps and `deleted_at`.

### `extensions`

- `id`, `name`, `path`, `manifest_version`, `enabled`, timestamps.

### `profile_extensions`

- Composite primary key `profile_id`, `extension_id`.

### `runtime_sessions`

- `id`, `profile_id`.
- `state`.
- Manager PID and browser PID when known.
- `started_at`, `stopped_at`.
- `exit_code` nullable.
- `last_message`, sanitized.

### `diagnostic_runs`

- `id`, `kind`, nullable `proxy_id`, nullable `profile_id`.
- `state`, `summary_json`, `artifact_path`, timestamps.

### `audit_events`

- `id`, `kind`, nullable profile/proxy ID, sanitized detail JSON, timestamp.

This local audit table records manager operations, not browsing history or page content.

## 13. REST API contract

Prefix every route with `/api/v1`.

### Application

- `GET /health`
- `GET /app/bootstrap`
- `GET /app/version`

### Authentication

- `GET /auth/status` is public and reports only whether first-run setup is required.
- `POST /auth/setup` is public only while no owner exists; it creates the single owner and initial session.
- `POST /auth/login` accepts local email and password. It returns safe owner/session metadata and a CSRF token while setting the opaque session token as an `HttpOnly` cookie.
- `POST /auth/logout` revokes the current session.
- `POST /auth/lock` revokes all sessions.
- `POST /auth/change-password` requires the current password, stores a new Argon2id hash, and revokes all sessions.
- `GET /auth/session` returns the authenticated owner email and CSRF token. Sessions have no time-based expiry metadata.

All non-authentication `/api/v1` routes require an active owner session. WebSocket connections use the same session cookie and exact Origin validation. Authentication tokens never appear in query strings or local storage.

### Profiles

- `GET /profiles`
- `POST /profiles`
- `POST /profiles/quick-create`
- `GET /profiles/{id}`
- `PATCH /profiles/{id}`
- `POST /profiles/{id}/duplicate`
- `POST /profiles/{id}/regenerate-fingerprint`
- `POST /profiles/{id}/start`
- `POST /profiles/{id}/stop`
- `POST /profiles/{id}/focus-window`
- `POST /profiles/{id}/move-to-trash`
- `POST /profiles/{id}/restore`
- `GET /profiles/{id}/logs`
- `GET /profiles/{id}/export`
- `POST /profiles/import`
- `POST /profiles/{id}/cookies/import`
- `GET /profiles/{id}/cookies/export`
- `POST /profiles/bulk`

`GET /profiles` accepts `query`, `folder_id`, `tag_id`, `workflow_status_id`, `runtime_state`, `proxy_reputation`, `pinned`, `sort`, `page`, and `page_size`.

### Folders/tags/statuses

- CRUD routes under `/folders`, `/tags`, and `/workflow-statuses`.
- Reorder endpoints accept an ordered list of IDs.

### Proxies

- `GET /proxies`
- `POST /proxies`
- `GET /proxies/{id}`
- `PATCH /proxies/{id}`
- `DELETE /proxies/{id}`
- `POST /proxies/parse`
- `POST /proxies/{id}/quick-test`
- `POST /proxies/{id}/quality-test`
- `GET /proxies/{id}/reports`

Proxy responses contain:

```json
{
  "id": "uuid",
  "label": "US account proxy",
  "scheme": "socks5h",
  "host": "proxy.example",
  "port": 1080,
  "username": "masked-or-safe-display",
  "has_password": true,
  "masked_endpoint": "socks5h://***:***@proxy.example:1080"
}
```

No response contains `password`.

### Diagnostics/settings

- `GET /diagnostics`
- `GET /diagnostics/{id}`
- `POST /diagnostics/direct-google-control`
- `POST /diagnostics/pixelscan`
- `GET /settings`
- `PATCH /settings`

### Errors

Use one envelope:

```json
{
  "error": {
    "code": "profile_already_running",
    "message": "This profile is already running.",
    "field_errors": {},
    "request_id": "uuid"
  }
}
```

Messages must be safe for display and must not contain raw credentials or credential-bearing proxy URLs.

## 14. WebSocket event contract

Endpoint: `/api/v1/events?token=<local-token>`.

Event envelope:

```json
{
  "event": "profile.runtime.changed",
  "sequence": 184,
  "timestamp": "2026-07-21T12:00:00Z",
  "data": {}
}
```

Events:

- `profile.created`
- `profile.updated`
- `profile.deleted`
- `profile.runtime.changed`
- `profile.runtime.message`
- `proxy.updated`
- `proxy.test.progress`
- `proxy.test.completed`
- `diagnostic.progress`
- `diagnostic.completed`
- `manager.reconciliation.completed`

On reconnect, the frontend refetches server state. Events are invalidation/status signals, not the sole source of persistent data.

## 15. Process lifecycle

- One profile may have at most one owned runtime session.
- Start acquires an in-process profile lock and a filesystem lock below the profile directory.
- Reconcile database sessions against owned PIDs at manager startup.
- Never terminate a PID solely because it exists in the database; verify process ownership and creation time.
- Start validates profile consistency and optionally tests the proxy.
- Start launches a persistent context with the profile's dedicated `user-data` directory, `fingerprint_preset="consistent"`, stable seed, proxy, GeoIP, extensions, and configured options.
- Stop asks the context to close, waits, then escalates only to verified owned child processes.
- Browser crashes produce `crashed` state and a sanitized runtime event.
- Backend shutdown attempts graceful closure but does not delete profile data.

## 16. Frontend/backend responsibility boundary

### Frontend owns

- Layout, responsive behavior, theme, tables, drawers, dialogs, forms, client-side validation hints, loading states, optimistic presentation where safe, and API mocks.
- It may cache server responses but never treats cached runtime status as authoritative.
- It never constructs Chromium commands or reads the filesystem directly.

### Backend owns

- Authoritative validation and persistence.
- Profile/folder/proxy/tag/status CRUD.
- Fingerprint generation and consistency validation.
- Filesystem paths and safe imports/exports.
- Credential storage and proxy relay.
- Process ownership, launch/stop/focus, runtime state, and logs.
- Proxy and browser diagnostics.
- Secret redaction and audit records.

### Shared contract

- OpenAPI generated by FastAPI is canonical.
- Backend keeps `/api/v1` backward compatible during version 1.
- Frontend generates or hand-maintains types against the checked-in OpenAPI fixture.
- Mock API data must match these schemas and may contain only documentation IP ranges and fake credentials.

## 17. Frontend implementation milestones

1. App shell, sidebar, header, routing, theme.
2. Profiles table with mock data, column settings, filters, pagination, runtime states.
3. Row overflow menu and confirmation dialogs.
4. Create/edit profile wizard.
5. Proxy library and editor/test result views.
6. Folders, Diagnostics, Settings.
7. Replace mocks with generated API client and WebSocket events.
8. Accessibility, empty/error states, responsive minimum-width behavior, tests.

The desktop dashboard targets 1280px and wider first. At narrower widths, the sidebar collapses and the profile table scrolls horizontally; the table does not collapse into cards in version 1.

## 18. Backend implementation milestones

1. Manager package, configuration, loopback security, health/bootstrap APIs.
2. SQLAlchemy models, migrations, repositories, recovery manifests.
3. Profile/folder/tag/status CRUD and validation.
4. Windows Credential Manager integration and proxy CRUD.
5. Fingerprint template generator and profile wizard validation API.
6. Owned process/session manager and runtime events.
7. Proxy quick/full diagnostics integration.
8. Cookie/profile import/export and application trash.
9. Production static frontend serving, startup command, recovery/reconciliation tests.

## 19. Acceptance criteria

- Create ten Windows profiles with distinct stable seeds and isolated user-data directories.
- Start and stop several different profiles; reject a second start of the same profile.
- Persist cookies and browser storage across restarts.
- Assign Direct, HTTP(S), SOCKS5, and SOCKS5H configurations through reusable proxy records.
- Never expose proxy passwords through REST, events, logs, SQLite, profile manifests, or Chromium process arguments.
- Search, filter, sort, paginate, pin, tag, folder, duplicate, export, trash, and restore profiles.
- Show live runtime state without manual refresh.
- Run proxy quick/full tests and open their artifacts.
- Prevent unsupported OS/browser personas and contradictory fingerprint settings.
- Recover safely after manager or browser crashes.
- Bind only to loopback and reject unauthorized mutation/origin requests.
- Pass backend tests and frontend component/API-contract tests.

## 20. Deferred features

- Team accounts, sharing, transfer, workspaces, permissions.
- Cloud profile storage or synchronization.
- Subscription, billing, proxy marketplace, advertisements.
- macOS/Linux manager support.
- Android/iOS personas.
- Alternative browser engines or branded browser personas.
- Full visual cookie editor.
- Bookmark manager.
- Automation builder and multi-profile action synchronization.
- Packaged auto-updater and signed Windows installer.

## 21. Reference interpretation

The supplied screenshots are interaction references only:

- Dense profile list with fixed navigation.
- Slide-over proxy editor and expanded test result.
- Grouped row overflow actions.
- Multi-step profile creation wizard.

Do not copy third-party logos, subscription banners, advertisements, proxy-store tabs, colors, copywriting, or proprietary assets. Use an original CloakBrowser visual system.
