# Local data ownership — profiles stay on the user's machine

**Status:** design. Confirmed facts are cited to current source; recommendations are marked.
Companion to [desktop-packaging.md](desktop-packaging.md) (how the app ships) and the licence
blocker in [activation-and-entitlements](activation-and-entitlements.md) (engine ≠ product licence).

## Principle

**All browser data and profiles live on the user's Windows computer. The cloud stores only
account, licence, device, and (optionally) anonymous counts — never browser data.** The desktop
already behaves this way; the cloud layer is additive and must not change it.

## Confirmed today (source-grounded)

- **Data root** defaults to `%LOCALAPPDATA%\CloakBrowser\Manager` (`config.py:10-14`); profiles under
  `data_root/profiles` (`config.py:41-42`); each profile dir = `profiles/<profile.id>`
  (`launcher.py:72`); the Chrome `--user-data-dir` is a `user-data` subfolder inside it
  (`launcher.py:529,533`) → `…\profiles\<id>\user-data`.
- **SQLite** manager DB at `data_root/manager.db` (`db.py:28-29`), WAL + FK + busy_timeout
  (`db.py:31-37`), Alembic-owned schema (`db.py:84-103`).
- **Secrets in the OS keyring, not SQLite** — `KeyringCredentialStore` stores `{username,password}`
  under service `cloakbrowser-manager-proxy` (`credentials.py:49-65`); the DB row holds only an opaque
  `credential_ref` uuid (`models.py:118`) — **no proxy password column anywhere**.
- **Profile IDs are UUID4** (`models.py:30-31,188`) → globally unique with no coordination; also a
  unique `fingerprint_seed` (`models.py:199`).
- **Per-profile file lock** `…\profiles\<id>\.runtime.lock` via `O_EXCL` (`locks.py:18-27`).
- **No device or cloud binding exists** — storage is purely local; nothing syncs, activates remotely,
  or hardware-locks a profile (verified absent across runtime/profile/proxy/config).
- **Backups are DB-only** — a `VACUUM INTO` snapshot of `manager.db` + a SHA-256 manifest; **browser
  profile directories are explicitly excluded** (`backups/service.py:8-10`).
- **Profile export is metadata-only** — `cloakbrowser-manager-profile` v1 carries profile settings +
  proxy endpoint (scheme/host/port, **no credentials**) + extensions by identity; **no cookies**
  (`portability/profiles.py`, `schemas.py:13-14`).
- **The CloakBrowser engine binary** is cached separately at `~/.cloakbrowser/` (auto-downloaded,
  self-verified Ed25519→SHA256) — **not** inside the profile store and never bundled.

## Ownership matrix

| Data | Where it lives | Cloud stores it? |
|---|---|---|
| Profile metadata (name, folder, fingerprint config, window/behavior, startup URLs) | local SQLite `manager.db` | **No** (optionally an anonymous *count* only) |
| Fingerprint seed / revision / config hash | local SQLite | No |
| Proxy row (scheme/host/port/label/geo/quality) | local SQLite | No |
| **Proxy username/password** | **local OS keyring** (`credential_ref`) | **Never** |
| Browser cookies, localStorage, cache, IndexedDB, service workers | `…\profiles\<id>\user-data` on disk | **Never** |
| Website logins / sessions / OAuth tokens | inside the profile's `user-data` (browser-managed) | **Never** |
| Extensions (unpacked dirs) + assignments | on disk + SQLite rows | No |
| Runtime session history, logs, diagnostics, resource samples | local SQLite / local files | No |
| Local backups (`VACUUM INTO` of manager.db) | `…\backups\*.zip` | No |
| CloakBrowser engine binary | `~/.cloakbrowser/` (per-user, from CloakHQ) | No |
| Account (email, argon2id hash), sessions, devices, licence, entitlements | **cloud PostgreSQL** | Yes |
| CloakBrowser engine licence key (if Pro) | **local** Windows-protected store (DPAPI/keyring), never embedded | No — see licence blocker |

**Forbidden in the cloud (default):** cookies, website credentials, proxy passwords, browser
localStorage/history, raw profile directories, OAuth tokens, extension private data, CloakBrowser
`user-data`. This mirrors the existing backup/export exclusions.

## Recommended v1 storage layout (under the Plasma rename)

```
%LOCALAPPDATA%\Plasma\
  state\            app/window state, install-token (per-process token preferred at runtime)
  db\manager.db     SQLite (WAL) — profile + proxy + runtime metadata
  profiles\<id>\
      user-data\    the Chrome --user-data-dir (cookies/cache/localStorage/etc.)
      .runtime.lock O_EXCL single-launch lock
      last-session.json  tab-restore list
  extensions\       registered unpacked extensions
  backups\          VACUUM INTO snapshots + manifests
  diagnostics\ logs\ update-staging\
```
Secrets (proxy creds, Pro engine key, cloud refresh token, device private key) stay in
**Windows-protected storage** (Credential Manager / DPAPI), never in `db\` or `state\`.
(`data_root` is absolute, so the backend finds the same store regardless of CWD — confirmed today.)

## Lifecycle rules (recommendation)

- **Logout / licence expiry / device revocation:** lock *launches* (entitlement gate), keep **all**
  local profiles and data intact. Never delete on expiry. Allow export/backup + subscription
  recovery. (Aligns with the offline-mode policy.)
- **App upgrade:** `data_root` is untouched; Alembic migrates `manager.db` to head on next start,
  **after** the existing auto-backup. Profiles/keyring survive.
- **Reinstall / repair:** never touch `data_root`; profiles persist. A fresh install with an existing
  `data_root` re-adopts the profiles as-is.
- **Uninstall:** ask a **separate, explicit** question — *"Delete your local browser profiles?"*,
  default **Keep**. Keep → remove app + `state/logs/update-staging`, leave
  `profiles/db/backups`. Delete → also remove those after a second confirm. Never silent.
- **Different computer / same account:** profiles do **not** follow (v1 is local-only). The cloud
  authenticates the user and enforces limits; it does not hold profiles. This is a deliberate v1
  choice — see below.

## Device-binding & sync stance (v1)

- **Profiles are local-only and not device-bound in the cloud.** Rationale: it keeps the cloud free
  of all browser data (smallest attack surface + simplest compliance), matches today's behavior, and
  avoids a sync protocol we'd have to secure. **Classification: keep local-only for v1.**
- The cloud may store an **anonymous profile count** per device purely to enforce a plan's
  `profile_limit` — a number, never names or metadata. Enforcement is best-effort (a patched client
  can lie), consistent with "don't assume client-side licensing is unbypassable."
- **Future (postpone):** optional **end-to-end-encrypted** profile sync — the client encrypts a
  profile bundle under a user-held key the server can't read, so the server stores ciphertext only.
  Design later; not needed for the first customers.

## How this ties to packaging

The Tauri shell + PyInstaller backend ([desktop-packaging.md](desktop-packaging.md)) simply point the
backend at `%LOCALAPPDATA%\Plasma` via `CLOAK_MANAGER_DATA_ROOT`. The engine binary still
auto-downloads to `~/.cloakbrowser` and self-verifies — **not** bundled (both a technical and a
licence requirement). Nothing about local storage requires the cloud to be reachable: with a valid
cached entitlement inside the offline grace window, the whole local profile store opens and runs
offline.
