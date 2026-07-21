# CloakBrowser Manager Competitor Functionality Matrix

Research date: July 21, 2026. Sources are official product documentation unless explicitly noted. This document separates features worth adopting from cloud/team complexity that does not fit CloakBrowser's local single-user version 1.

## Product Direction

CloakBrowser should combine:

- Hidemium's efficient profile list and smart bulk proxy assignment.
- GoLogin's clear profile lifecycle, bulk action discoverability, and safe IP-aligned defaults.
- BitBrowser's broad local API and granular profile controls.
- CloakBrowser's source-level Chromium fingerprint patches, local ownership, and credential-safe diagnostics.

We should not copy competitor fingerprint controls that the installed CloakBrowser binary cannot honestly enforce. The manager must expose only verified engine capabilities.

## Functionality Matrix

| Area | GoLogin | BitBrowser | Hidemium | CloakBrowser direction | Priority |
|---|---|---|---|---|---|
| Profile list | Search, folders, tags, notes, pin, status, run/stop | Search, groups, remarks, sequence, paging | Search, folders, status, table actions | Existing list/filter/catalog backend; finish runtime state and actions | P0 |
| Create profile | Quick, custom, up to 30 bulk profiles | Single, batch import/add, random fingerprint | Multi-section create wizard | Windows-only quick/custom creation; add bulk-create preview | P1 |
| Profile-owned proxy | Custom or built-in proxy attached to profile | Proxy fields stored on browser profile | Proxy configured inside profile editor | One proxy config per profile, credentials outside SQLite | P0 |
| Smart bulk proxy | Bulk assign/change; proxy list also available | Batch profile-proxy update | Select profiles, paste/select proxies, pair and update | Paste proxies, preview deterministic mappings, apply to selected profiles | P0 |
| Proxy check | Checks on assignment | `/checkagent` availability and IP query | Check Proxy returns IP/location | Quick check: reachability, exit IP, latency, geo/ASN; quality check separately | P0 |
| Proxy quality | Basic status/provider data | Basic detection service | Basic live/location check | Add existing reputation/type/Google/Cloudflare scanner with scope disclaimer | P1 |
| IP-aligned identity | Auto timezone and geolocation from external IP | IP-derived timezone, geolocation, language | Timezone, WebRTC, geolocation, language from proxy IP | Default locale/timezone/WebRTC/geolocation consistency to proxy evidence | P0 |
| Fingerprint generation | New fingerprint and bulk refresh | Random fingerprint and many manual fields | New profile fingerprint sections | Stable secure seed plus supported consistent preset; verify before exposing controls | P0 |
| Fingerprint diagnostics | Limited user-facing verification | Manual granular settings | Proxy/fingerprint configuration UI | First-party snapshot stability/difference checks and Pixelscan evidence | P1 |
| Cookies | Import/export/delete; isolated and cloud-synced | Create-time cookie, live get/set/clear, batch import/export | Cookie step and profile persistence | Local import/export/clear with JSON/Netscape validation; no cloud sync | P1 |
| Extensions | Per-profile, custom unpacked, defaults for new profiles, bulk edit | Extension/data sync controls | Suggested/uploaded extensions assigned to profiles | Local unpacked extension library plus per-profile/bulk assignment | P1 |
| Bookmarks | Per-profile and bulk edit | Bookmark sync | Per-profile bookmark section | Local bookmark library plus profile/bulk assignment | P1 |
| Startup URLs | Profile settings | Multiple launch URLs | New-profile requests/bookmarks | Already modeled; add editor and bulk update | P0 |
| Duplicate/clone | Clone profiles | Batch/profile APIs | Copy action in list | Existing duplicate API; make copied identity/credentials behavior explicit | P0 |
| Bulk actions | Run/stop, folders, proxy, share, tags, extensions, bookmarks, rename, clone, transfer, export, fingerprint, delete, automation | Partial update, group/proxy/remark, close/delete/cache, cookies | Proxy, folders, update multiple, export/import | Selection bar with safe preview for destructive or identity-changing actions | P0/P1 |
| Runtime control | Run/stop and cloud sessions | Open/close, PID, ports, abnormal-state reset | Local API open/close with remote port/path | Owned process lifecycle, PID reconciliation, start/stop/restart, typed failures | P0 |
| Window arrangement | Multi-profile launch/sync | Grid/diagonal/adaptive multi-monitor arrangement | Display-window action | Add arrange-grid after runtime foundation | P2 |
| Folders/tags/status | Folders and tags | Groups and remarks | Folders and statuses | Existing folders/tags/status; keep local | P0 |
| Trash/recovery | Recover deleted profiles for a limited time | Direct deletion/clear operations | Delete/export workflows | Existing soft trash; add permanent purge and retention settings | P1 |
| Profile export/import | Export through bulk actions | Profile/cookie batch export/import | Local profile folder export/import with failure counts | Encrypted local backup/export with progress and partial-failure report | P1 |
| Synchronization | Cloud sync across devices; team collaboration | Tabs/cookies/storage/history/extensions sync options | Cloud/local profiles and synchronizer | Do not build cloud sync in local single-user v1 | Exclude v1 |
| Sharing/transfer/team | Share, workspace, transfer | Subusers/transfer | Share folders/accounts | Do not build until multi-user/cloud product exists | Exclude v1 |
| Automation | Bulk automation and API/cloud browser | RPA run/stop, local API, utilities | Visual automation and local API | Stable local REST/WebSocket first; optional automation workflows later | P2 |
| Audit/session history | Profile history and status | Runtime status/PIDs | Logs and status columns | Sanitized local audit events and runtime history | P1 |
| Security | Account/cloud auth | Local/cloud account controls | Account login | Single local owner, Argon2id, revocable persistent session, Credential Manager | P0 |

## Smart Bulk Proxy Assignment

The feature remains profile-owned. There is no proxy inventory table or proxy paging screen.

### User flow

1. Select profiles in the profile table.
2. Choose **Update Proxy** from the bulk action bar.
3. Paste one or more lines using URL, `host:port`, `host:port:user:password`, `user:password@host:port`, or Hidemium-style `TYPE|HOST|PORT|USERNAME|PASSWORD`.
4. Choose a mapping rule.
5. Review a table showing profile name, parsed protocol, masked endpoint, mapping status, and validation errors.
6. Optionally run bounded checks before applying.
7. Apply valid rows and receive a per-profile success/failure report.

### Mapping rules

- **One proxy → all selected profiles:** allowed but warns that shared IPs may link identities.
- **Same count:** map profile 1 to proxy 1, profile 2 to proxy 2, and so on. This is the recommended default.
- **Fewer proxies than profiles:** do not silently reuse. Require explicit **Round robin** selection and display a linkage warning.
- **More proxies than profiles:** map the first N proxies and report unused lines before apply.
- **Clear proxy:** set selected profiles to Direct after confirmation.

The preview uses a short-lived server-side token containing only hashes and normalized non-secret metadata. Raw proxy lines and credentials remain in frontend memory until apply. Apply sends explicit profile/proxy pairs, mirroring Hidemium's batch API rather than relying on positional state that could change after sorting or filtering.

### API shape

- `POST /api/v1/profiles/proxy/bulk-preview`
- `POST /api/v1/profiles/proxy/bulk-apply`

`bulk-preview` validates a maximum of 100 profiles/proxies and returns masked mappings. `bulk-apply` requires the preview token, explicit profile IDs, and credentials, then performs independent credential-store/database compensation per profile. It returns `updated`, `failed`, and safe row-level error codes; one failed proxy does not corrupt successful assignments.

## Recommended Delivery Order

### P0 — usable local manager

1. Owned profile start/stop/runtime reconciliation.
2. Profile-owned proxy editor, quick test, and smart bulk assignment.
3. Create/edit wizard wired to existing profile fields.
4. Profile list actions, bulk folder/tag/status/pin/trash, startup URLs.
5. Proxy-aligned locale, timezone, geolocation, and WebRTC at launch.

### P1 — operational parity

1. Cookie import/export/clear.
2. Extension and bookmark libraries with bulk assignment.
3. Proxy quality and fingerprint diagnostics.
4. Local profile backup/import with progress and partial failures.
5. Audit/runtime history and permanent trash purge.

### P2 — productivity expansion

1. Window arrangement and multi-profile launch queue.
2. Local automation API/WebSocket and reusable workflows.
3. Optional profile templates.

Cloud sync, teams, sharing, transfer, subscriptions, and integrated proxy sales are intentionally excluded from local single-user version 1.

## Sources

- GoLogin bulk actions: https://support.gologin.com/en/articles/14323620-bulk-actions
- GoLogin profile settings: https://support.gologin.com/en/articles/14854406-profile-settings
- GoLogin cookies: https://support.gologin.com/en/articles/14363118-cookies-import-and-export
- GoLogin extensions: https://support.gologin.com/en/articles/14403896-adding-browser-extensions-to-profiles
- GoLogin synchronization: https://support.gologin.com/en/articles/14404855-profile-synchronization
- BitBrowser profile/API capabilities: https://doc.bitbrowser.net/api-docs/browser-profiles
- BitBrowser profile creation: https://doc.bitbrowser.net/help1/browser-profiles/add-a-new-browser-profile
- BitBrowser profile functions: https://doc.bitbrowser.net/help1/browser-profiles/features-and-functions
- Hidemium bulk proxy change: https://docs.hidemium.io/features-of-hidemium/profiles/change-proxy
- Hidemium batch proxy API: https://docs.hidemium.io/hidemium-4/i.-bat-dau-voi-hidemium/api-automation-v4/proxy/2.-update-profiles-proxy
- Hidemium proxy manager and bulk tutorial: https://education.hidemium.io/courses/basic-guide-to-using-hidemium-version-4/lessons/lession-12-proxy-managercopy/
- Hidemium profile settings: https://docs.hidemium.io/features-of-hidemium/new-profile/main
- Hidemium folders: https://docs.hidemium.io/features-of-hidemium/folders
- Hidemium extensions: https://docs.hidemium.io/features-of-hidemium/new-profile/extensions
- Hidemium local export/import: https://docs.hidemium.io/hidemium-4/ii.-thiet-lap-va-cau-hinh-he-thong/huong-dan-su-dung-chuc-nang-export-import-profile-local
