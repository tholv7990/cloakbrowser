# Backend contract — Backups (`/backups`)

**Owner:** backend (Codex). Frontend is built (a "Backups" section in Settings, `features/settings/BackupsSection.tsx`, EN/VI).

**Reference:** `Quantum-Source-Clean-*/backend/services/backup_service.py`, `backend/api/backups.py`.

## Goal

Verified local snapshots of **manager metadata** (the SQLite DB + proxies/workspaces/extensions), so a bad edit or migration can be rolled back. **Never** back up browser profile folders / cookies / sessions.

## Endpoints (`features/backups/routes.py`, prefix `/api/v1/backups`)

```
GET    /backups              -> 200 BackupArchive[]        # newest-first
POST   /backups              -> 201 BackupArchive          # create now (manual)
POST   /backups/{id}/restore -> 200 {} / 204               # restore (see safeguards)
DELETE /backups/{id}         -> 204
```

Same session/origin auth as other routes.

## Response shape

Mirror `BackupArchive` in `manager/frontend/src/types/api.ts`:

```jsonc
{
  "id": "bkp_...",
  "created_at": "2026-07-22T09:00:00Z",
  "size_bytes": 2400000,
  "automatic": true,                 // startup auto-backup vs manual
  "verified": true,                  // hash + SQLite integrity check passed
  "contents": ["profiles", "proxies", "workspaces", "extensions"]
}
```

## Data model + storage

- Archives live under `<cache/data dir>/backups/` (env-overridable, e.g. `CLOAKBROWSER_CACHE_DIR`). Each archive is a single file (zip) containing: the SQLite DB snapshot, the proxy/workspace/extension JSON mirrors, and unpacked extension files, plus a manifest with per-file SHA-256.
- Metadata can be a small `backup_archive` table (id, created_at, size_bytes, automatic, verified, contents_json, path) **or** derived by scanning the backups dir + reading each manifest. A table is simpler for `GET`.

## Implementation

- **Create** (mirror `backup_service`): checkpoint WAL, snapshot SQLite (`VACUUM INTO` or a consistent file copy), bundle the mirrors + extension files, write per-file SHA-256 into a manifest, zip it, and record `verified=true` after re-reading + hashing. Explicitly **exclude** browser profile directories.
- **Automatic backup**: on app **startup (lifespan)**, if the latest archive is older than 24h, create one (`automatic=true`). Retention: keep the latest 10, delete older.
- **Restore** (destructive — guard hard): (1) require all runtimes **stopped** (reject 409 otherwise — use the runtime layer to check); (2) verify every file hash + run `PRAGMA integrity_check` on the snapshot; (3) take a **pre-restore safety backup** first; (4) replace the SQLite DB + mirrors; (5) leave cookies/session/browser folders untouched. Return 200 on success, 409 if browsers are running, 422 if verification fails.
- **Delete**: remove the archive file + its metadata row.

## Security / safety

- Restore must never run while browsers are open, must always take a safety backup first, and must verify integrity before overwriting. Never include secrets that aren't already in the DB/mirrors (proxy passwords live in the secure credential store, not the DB — decide explicitly whether the backup references them; default is to back up metadata only and leave the OS credential store as the source of truth).

## Tests

`tests/manager/test_backups_api.py`: create → `verified=true`, archive excludes any browser-data path, `contents` lists the expected groups; restore is rejected (409) while a runtime is active; restore verifies hashes and takes a safety backup first (assert a new `automatic`/safety archive appears); delete removes it. Update `openapi.json` if checked in.
