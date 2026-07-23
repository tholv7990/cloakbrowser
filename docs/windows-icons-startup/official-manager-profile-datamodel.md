# Profile data-model comparison — official vs Plasma

OFFICIAL = `CloakBrowser-Manager` (Pydantic + raw sqlite). PLASMA (ours) = `manager_backend`
(SQLAlchemy ORM + keyring + normalized tables). Read-only. CONFIRMED = read in source.

**Bottom line:** Plasma's model is a generation ahead on data integrity, security, and
normalization. The official is a flat single-table design with a few genuinely useful *user-facing
fingerprint knobs* Plasma doesn't expose (OS/platform, spoofed screen resolution, GPU renderer).
Those are the only real adopt candidates; everything else is ours-ahead.

## 1. Official profile schema (single `profiles` table, `official: database.py:34-59`; Pydantic `models.py:10-32`)
Key fields: `id` (uuid), `name`, `fingerprint_seed` (INTEGER, **random 10000–99999**, `database.py:93`),
`proxy` (TEXT, **inline `http://user:pass@host:port`**, `models.py:13`), `timezone`, `locale`,
`platform` (win/mac/linux, → `--fingerprint-platform`, `browser_manager.py:391-394`), `user_agent`,
`screen_width/height` (1920/1080 → `--fingerprint-screen-*`, `browser_manager.py:408-413`),
`gpu_vendor`/`gpu_renderer` (`browser_manager.py:396-402`), `hardware_concurrency`,
`humanize`/`human_preset`, `headless`, `geoip`, `clipboard_sync`, `auto_launch`
(`browser_manager.py:342-362`), `color_scheme`, `launch_args` (**unvalidated**, `database.py:76`),
`notes`, `tags` (via `profile_tags`, `database.py:61-66`), `user_data_dir`, `created_at`/`updated_at`.
**No** folders, soft-delete, session history, fingerprint versioning, or unique-seed constraint.

## 2. Plasma profile schema (`ours: models.py:170-250`; `schemas.py:124-188`)
Flat identity columns + three JSON sub-objects. Highlights: `fingerprint_seed` (String(20),
**UNIQUE**, 64-bit, `models.py:199`), `fingerprint_preset`, `fingerprint_revision`,
`fingerprint_config_hash` (sha256 of canonical config, `fingerprints.py:43-72`), `browser_version_mode`
+ `browser_version` (Quantum tier), `user_agent_mode` + `custom_user_agent`, `location` JSON
(geo_mode, locale, timezone, webrtc_mode, geolocation_mode, lat/long/accuracy, `schemas.py:33-62`),
`window` JSON (mode, width, height, color_scheme), `behavior` JSON (humanize, clear_cache,
restore_tabs, permissions, ignore_https_errors, hw_concurrency mode+val, gpu mode+vendor,
additional_args), `proxy_id` (FK→proxies **RESTRICT**, `models.py:218-220`),
`test_proxy_before_launch`, `last_opened_at`, `total_runtime_seconds`, `deleted_at` (**soft delete**).
Related tables (Plasma-only): Folder, WorkflowStatus, Proxy + ProxyQualityRun, Extension (M2M),
DiagnosticRun, RuntimeSession (pid/cdp/exit history), ProfileLogEntry, MediaAsset, Automation/Shopify.
Patch payload carries `expected_updated_at` (optimistic concurrency, `schemas.py:191-192`).

## 3. Side-by-side

**Fields THEY have that WE don't (adopt candidates):**

| Field | Official | Plasma status | Verdict |
|---|---|---|---|
| **`platform`** OS spoof | `models.py:16` | `--fingerprint-platform` reserved (`ours: schemas.py:17`) but **never emitted** (0 hits in `features/runtime`) | **Adopt (M)** |
| **`screen_width/height`** (spoofed screen res) | `models.py:18-19` | only `window.width/height` = window size; screen locked 1920×1080 by preset (`ours: launcher.py:264-275`) | **Adopt (M)** |
| **`gpu_renderer`** + GPU preset library | `models.py:21` | we store `behavior.gpu_vendor` only | **Adopt (S)** |
| `auto_launch` | `models.py:28` | absent | Adopt (S), optional |
| `headless` per profile | `models.py:25` | runtime hard-codes headed (`ours: launcher.py:536`) | Skip |
| `clipboard_sync` | `models.py:27` | N/A (not VNC) | Skip |

**Fields WE have that THEY don't (our advantages):** unique 64-bit seed + DB constraint
(`ours: models.py:199`, `fingerprints.py:75-80`); config hash + revision (`fingerprints.py:43-72`);
browser-version pin (`models.py:205-206`); keyring proxy creds (`credentials.py:49-87`); normalized
Proxy with geo/quality metrics (`models.py:104-136`); WebRTC modes + manual geolocation
(`schemas.py:40-62`); folders + Kanban status; soft-delete/trash; optimistic concurrency; extensions,
media, runtime-session history, per-profile audit log; validated startup_urls + tab restore;
manager-owned-arg rejection on additional_args (`schemas.py:96-105`).

## 4. Fingerprint representation
- **Official:** seed + ~7 explicit flat override columns, each 1:1 to a `--fingerprint-*` flag
  (`browser_manager.py:379-415`). Flexible manual overrides; no hash, no revision, no uniqueness.
- **Plasma:** seed (unique 64-bit) + preset + `fingerprint_config_hash`/`revision` over the full
  canonical config; at launch only `--fingerprint=<seed>` + `--fingerprint-webrtc-ip` emitted, the
  binary derives the rest. Fewer knobs, tamper-evident + versioned.
- **Verdict:** identity integrity → Plasma; manual-override breadth → official. Graft the official's
  three knobs onto ours and fold them into `fingerprint_config_hash`.

## 5. Proxy
- **Official:** embedded **plaintext** `proxy TEXT` with inline creds (`models.py:13`,
  `database.py:38,109`); one per profile, no metadata.
- **Plasma:** `proxy_id` FK → normalized Proxy (`ON DELETE RESTRICT`); creds in OS keyring behind
  `credential_ref`, never in the DB (`models.py:118`, `credentials.py:49-87`); rich quality/geo
  metadata. **Plasma decisively better.**

## 6. Geo / timezone / locale / WebRTC / language
- **Official:** flat `timezone`+`locale`+`geoip` bool; no WebRTC control, no geolocation coords.
- **Plasma:** `location` JSON with geo_mode, WebRTC modes, geolocation_mode + validated lat/long
  (`schemas.py:33-62`); proxy-derived geo is the default; stale manual values not leaked when
  mode≠manual (`ours: launcher.py:88-94`); WebRTC exit-IP spoof wired (`:288-296`). **Plasma richer +
  safer.**

## 7. Fingerprint uniqueness / seed handling
- **Official:** `random.randint(10000, 99999)` — 90k space, **no unique constraint**
  (`database.py:93`; FE `ProfileForm.tsx:142-144`). **INFERRED:** ~50% collision by ~350 profiles,
  near-certain in the low thousands — silent cross-account correlation risk.
- **Plasma:** `secrets.randbits(64)` via `generate_unique_seed()` with retry (`fingerprints.py:75-80`)
  + DB `unique=True` (`models.py:199`). **Plasma wins outright.**

## 8. Adopt recommendations (ranked)
1. **Per-profile OS/platform spoof** (`official: models.py:16`) — **M** — biggest anti-detect gap;
   `--fingerprint-platform` already reserved.
2. **Spoofed screen resolution + presets** (`official: models.py:18-19`) — **M** — breaks the uniform
   1920×1080 fleet fingerprint; fold width/height into `fingerprint_config_hash`.
3. **GPU renderer + curated preset library** (`official: models.py:21`) — **S** — completes the GPU
   surface; better UX than free-text.
4. **`auto_launch`** — **S** — optional; weaker fit for a user-driven desktop app.
5. **First-launch detection-test bookmarks** — **S** — optional given our DiagnosticRun.

**Caveat:** items 1–3 assume the patched Chromium honors `--fingerprint-platform` /
`--fingerprint-screen-*` / `--fingerprint-gpu-renderer` as the official emits them — CONFIRMED the
official emits them and that `--fingerprint-platform` is reserved in our schema, but INFERRED (not
binary-verified here) that wiring them through "just works." Validate against the binary first.

## 9. Anti-patterns in the official — do NOT copy
Plaintext proxy creds in the DB (`database.py:38,109`); tiny non-unique seed range (`database.py:93`);
unvalidated `launch_args` (`models.py:30`, `database.py:76` — a user could pass `--user-data-dir`);
ad-hoc `ALTER TABLE` in `init_db` (`database.py:70-80`, no migration framework); hard delete + rmtree
(`main.py:500-519`); no optimistic concurrency (`main.py:482-497`); flat nullable fingerprint columns
with no hash/version; loose response typing (`models.py:77,85`).

## Things where Plasma is already ahead — keep
Unique 64-bit `secrets` seed + DB constraint; hashed/revisioned fingerprint identity; keyring proxy
creds + normalized Proxy with metrics; rich `location`/WebRTC with launch-time leak guards; folders,
Kanban, soft-delete, optimistic concurrency; extensions, media, runtime-session history, audit logs;
validated startup_urls + tab restore; manager-owned-arg rejection; browser-version pin (Quantum
free/Pro-seat tier).
