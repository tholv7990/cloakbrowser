# Backend contract — Media engine (`/media`)

**Owner:** backend (Codex). Frontend is built (a `/media` screen, `features/media/MediaPage.tsx`, EN/VI, gated by a `media` capability).

**Reference:** `Quantum-Source-Clean-*/backend/services/media_engine.py`, `backend/api/media.py`, `backend/v65_engine/core/{media_manager,media_spoof}.py`.

## Goal

Manage a library of **virtual media sources** (camera / microphone / screen) that the browser engine injects in place of real devices (fake `getUserMedia`), plus a global on/off. The manager owns the **library + assignment + launch wiring**; the actual injection happens in the CloakBrowser engine at launch.

## Capability

Add `media: bool` to `AppCapabilities` in `features/app/routes.py` (the frontend nav-gates on it).

## Endpoints (`features/media/routes.py`, prefix `/api/v1/media`)

```
GET    /media/settings        -> 200 MediaSettings
PATCH  /media/settings        -> 200 MediaSettings          # { enabled }
GET    /media/assets          -> 200 MediaAsset[]
POST   /media/assets          -> 201 MediaAsset             # register an asset
DELETE /media/assets/{id}     -> 204
```

Same session/origin auth as other routes.

## Response shapes

Mirror `MediaSettings` and `MediaAsset` in `manager/frontend/src/types/api.ts`:

```jsonc
// MediaSettings
{ "enabled": false }

// MediaAsset
{
  "id": "media_...",
  "name": "Office webcam",
  "kind": "camera",                 // 'camera' | 'microphone' | 'screen'
  "format": "video/mp4",            // MIME type
  "size_bytes": 5800000,
  "assigned_profile_count": 2,      // derived from profile assignments
  "created_at": "2026-07-22T09:00:00Z"
}
```

The current frontend `POST /media/assets` body is `{ name, kind, format }` (registers a placeholder). If you support real file uploads, accept `multipart/form-data` (file + name + kind) and derive `format`/`size_bytes` from the upload — update the frontend contract note if so.

## Data model + storage

- `media_asset` table: `id`, `name`, `kind`, `format`, `size_bytes`, `path` (file on disk under `<data dir>/media/`), `created_at`.
- `media_settings`: single row `{ enabled }`.
- Asset↔profile assignment: a join table `profile_media_asset` (or reuse the profile's `behavior`/extra config). `assigned_profile_count` is a COUNT over it. (Per-profile assignment UI is a future addition — v1 frontend only shows the count; assignment can start empty.)

## Implementation

- Store uploaded media files under a data dir (env-overridable). Validate MIME type against `kind` (image/* or video/* for camera, audio/* for microphone) and cap size.
- **Launch wiring**: when a profile launches and `settings.enabled` and the profile has assigned media, pass the engine the media config (the CloakBrowser engine / `media_spoof` layer consumes it to fake the device). The manager's job is to resolve assigned assets → the launch config the engine expects; the spoofing itself is in the binary/engine (like fingerprints).
- Deleting an asset should also unassign it from any profiles.

## Notes

- Media files are content, not secrets — but validate/size-limit uploads. Nothing here returns a secret.
- The heavy lifting (actual `getUserMedia` substitution) is engine-side, mirroring how fingerprint patches live in the binary; the manager only curates the library and wires launch config.

## Tests

`tests/manager/test_media_api.py`: create → appears in `GET /media/assets` with `assigned_profile_count: 0`; `PATCH /media/settings {enabled:true}` round-trips; delete removes the asset (and any assignment); an invalid MIME/kind combination is rejected (422). Update `openapi.json` if checked in.
