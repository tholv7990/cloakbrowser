# 05 — Stability & Separation (Audit Task 6)

Two orthogonal properties:

- **Stability** — one profile presents the *same* identity across time/conditions (except where a
  field is explicitly allowed to change).
- **Separation** — different profiles are *plausibly distinct* without being *impossibly uniform* or
  *impossibly unique*.

The guiding rule from the brief: **"different" does not mean randomly changing every value.** Common
real-world values (screen 1920×1080, 8 cores, a popular GPU) *should* repeat across profiles;
forcing global uniqueness is itself a tell.

## Field stability classes

| Field | Class | Rationale |
|-------|-------|-----------|
| `fingerprint_seed` | MUST_BE_STABLE | the identity anchor; changes only via explicit regenerate |
| Canvas / WebGL / Audio hash | MUST_BE_STABLE (consistent preset) | noise off → deterministic per seed; **F-006/F-010 must confirm** |
| navigator.platform | MUST_BE_STABLE / HOST | Windows-only |
| hardwareConcurrency, deviceMemory, GPU | MUST_BE_STABLE | seed-derived; must not drift between calls/tabs |
| screen / DPR / color depth | MUST_BE_STABLE | per profile; **MAY_REPEAT across profiles** (F-010) |
| UA / Client Hints | MAY_CHANGE_WITH_BROWSER_VERSION | version bump changes them coherently |
| timezone / locale / WebRTC IP | MAY_CHANGE_WITH_NETWORK | proxy-derived; change only per explicit policy |
| geolocation coords | MAY_CHANGE_WITH_NETWORK | should track proxy city (once F-005 fixed) |
| cookies / storage / cache | MUST_BE_STABLE (persisted) | per-profile dir; survive restart |
| host public/local IP, host TZ, host fonts beyond persona, real GPU | MUST_NOT_EXPOSE_HOST | leak surfaces ([03](03-threat-model.md)) |
| cross-profile: seed, config hash | MUST_DIFFER | uniqueness anchors |
| cross-profile: screen, cores, GPU model, common UA | MAY_REPEAT | common real values are expected to collide |

## Stability suite — same profile

Each row is a test the harness must run and assert against the profile's first captured identity.

| Condition | What must hold | Notes / current coverage |
|-----------|----------------|--------------------------|
| Multiple calls on one page | Canvas/Audio/WebGL hashes identical | consistent preset (`--fingerprint-noise=false`); **default preset = noise on → NOT stable within a page (document)** |
| Multiple tabs | identical across tabs | per-context |
| Browser restart | identical (seed persists on disk + snapshot) | seed re-emitted from DB |
| Manager restart | identical | seed in SQLite |
| Windows restart | identical | seed in SQLite |
| Browser crash/recovery | identical; bounded tab restore | `launcher.py:230-262` |
| Manual vs automated launch | identical identity; **no extra automation tells in E vs D** | differential DT-AUTO ([04]) |
| Browser version upgrade | seed stable; UA/CH change **coherently** together | **gap: no test that a version bump preserves seed** (test audit #2) |
| Extension install | identity stable (extensions don't alter seed surfaces) | per-profile |
| Backup / restore | identity preserved | **gap: restore test asserts name only, not seed** (test audit #10) |
| Export / import | identity **intentionally reset** (fresh seed) | Confirmed non-invariant (`test_profile_portability.py:469`) |
| Duplicate | identity **intentionally fresh** | F-019; document as deliberate |

Two documented **non-invariants** (correct by design, must be labelled so no one "fixes" them):
export/import and duplicate deliberately mint a new identity to prevent accidental linkage.

## Separation suite — different profiles

- **≥100 profiles (CI):** generate 100 profiles, collect identities, assert:
  - 0 exact duplicate `(seed)` and 0 duplicate `fingerprint_config_hash` (MUST_DIFFER).
  - No two profiles share a seed (DB `unique=True` already guarantees; assert anyway).
  - Per-component duplicate **rates** within plausible bounds: seed 0%; Canvas/Audio hash near 0%
    (if the binary varies them per seed — this is exactly what F-010 must confirm); screen/cores/GPU
    **allowed to repeat** (report the rate, don't fail on it).
  - No **impossible correlation**: e.g. two profiles with identical Canvas hash but different seeds
    (would imply the seed doesn't drive Canvas), or a locale that never matches its timezone.
- **1,000 profiles (optional statistical, gated):** same checks at scale + a distribution report
  (entropy per surface, top-N most common values). This is where a truly fleet-constant surface
  (F-010 screen) shows up as a 100%-duplicate component.

### Explicit anti-requirements

- Do **not** require every profile to be globally unique on every surface. A 30% screen-resolution
  collision rate is *healthy* (1920×1080 is common). A **100%** collision on a surface that should
  vary per seed is the bug.
- Do **not** treat a shared common Canvas/WebGL hash as automatic failure — only if it is shared
  *with a different seed* (impossible correlation) or shared across the *entire* fleet.

## Duplicate-detection method

- Hash each collected identity into a canonical tuple `(seed, config_hash, canvas, webgl, audio,
  screen, cores, gpu, ua, tz, locale)`.
- **Exact-identity duplicates** (whole tuple equal, different profile ids) → hard fail.
- **Forbidden shared seed** → hard fail (should be impossible; guards the DB constraint).
- **Per-component duplicate rate** → report; fail only when a MUST_DIFFER component repeats or a
  MAY_REPEAT component hits an implausible extreme (e.g. 100% or a value no real device has).

## Coverage gaps to close (from the test audit)

1. No concurrent-create seed-collision/retry test (relies on DB constraint only) — add a threaded
   test that forces two auto-generated creates to race.
2. No test that a `browser_version` / binary bump preserves the seed — add one.
3. Timezone/locale asserted as snapshot data but never as **emitted launch flags** — add flag-level
   assertions (mirroring the existing WebRTC flag test `test_launcher.py:362`).
4. Backup/restore identity preservation asserts name only — assert `fingerprint_seed` too.
