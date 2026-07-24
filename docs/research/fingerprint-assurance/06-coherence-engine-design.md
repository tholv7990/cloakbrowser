# 06 — Coherence Engine Design (Audit Task 9)

Design only — **not for broad implementation during this audit**. The goal is a **Windows-only
canonical device model** that generates a single plausible device and derives every dependent field
from it, so a profile can never present a self-contradictory identity.

## Principle

Today the manager stores independent fields (`browser_version`, `custom_user_agent`, `window`,
`hardware_concurrency`, `gpu_vendor`, `location`) with no relationship between them, and only some
reach the browser ([01](01-current-control-matrix.md)). The coherence engine replaces the free-field
model with a **derived model**: a small set of *chosen* inputs (a device template + a seed +
network policy) deterministically produces *all* dependent fields, and a validator rejects
impossible combinations before they can be stored.

This is deliberately aligned with what the binary already owns. The engine's job is **coherence and
validation of the flags Plasma controls**, not re-implementing fingerprint spoofing in Python (that
stays in the binary, per CLAUDE.md and `PROFILE_FIELD_CAPABILITY_MATRIX.md`).

## Canonical device model (schema sketch)

```jsonc
{
  "schema_version": 1,                 // for migrations
  "device_template_id": "win11-mid-intel-1080p",  // chosen from a curated set
  "seed": "12345678901234567890",      // 64-bit CSPRNG, the noise anchor
  "os": { "family": "windows", "build_family": "win11-22h2" },   // Windows-only
  "browser": { "channel": "stable", "version_family": "146" },   // ties to the real binary
  "hardware": { "cores_bucket": 8, "memory_bucket_gb": 16, "gpu_class": "intel-iris-xe" },
  "display": { "screen": [1920,1080], "dpr": 1.0, "color_depth": 24 },
  "network_policy": {                  // the only per-launch-variable block
    "geo_source": "proxy",            // proxy | manual | system
    "webrtc": "proxy",                // proxy | direct | disabled
    "geolocation": "proxy"            // proxy | manual | block | ask
  },
  "derived": { /* computed, never hand-edited: UA, CH, locale defaults, window */ }
}
```

- **Chosen inputs:** `device_template_id`, `seed`, `network_policy`. Everything else is derived.
- **Curated templates:** a small set of *real, common* Windows device profiles (e.g. mid-range Intel
  laptop 1080p, high-end NVIDIA desktop 1440p) so values cluster like a real population (supports the
  MAY_REPEAT rule in [05](05-stability-and-separation.md)). Not hundreds of random combos.

## Derivation rules

| Derived field | Derived from | Constraint |
|---------------|--------------|-----------|
| UA + Client Hints | browser.version_family + os.build_family | UA, `Sec-CH-UA*`, `userAgentData` must all agree (fixes F-008) |
| navigator.platform | os.family | always `Win32`/`windows` |
| hardwareConcurrency | hardware.cores_bucket | only from a plausible bucket set {4,6,8,12,16} |
| deviceMemory | hardware.memory_bucket_gb | {4,8,16,32}; must be ≥ plausible for cores |
| GPU vendor/renderer | hardware.gpu_class | vendor/renderer strings from a real pair table |
| screen/DPR/color | display | window ≤ screen (fixes F-015) |
| window default | display.screen | maximized == screen; custom clamped ≤ screen |
| locale (default) | network_policy + proxy country | coherent map (fixes F-009) |
| timezone | proxy exit IP (proxy mode) | country fallback, never host (fixes F-002) |
| geolocation | proxy city centroid (proxy mode) | applied, not dropped (fixes F-005) |
| WebRTC IP | proxy exit IP | disabled actually disables (fixes F-001) |

## Validation rules (reject vs warn)

- **Reject (impossible):** custom UA whose platform ≠ Windows; pinned version not resolvable by the
  tier (F-011); window > screen (F-015); geolocation "manual" without coordinates (already enforced,
  `schemas.py:53-62`); hardware/GPU/screen combinations no real device has; a field marked
  `MUST_NOT_EXPOSE_HOST` set to a host value.
- **Warn (unusual but possible):** an uncommon-but-real cores/memory/GPU combination; a manual
  timezone that disagrees with the proxy country; `ignore_https_errors` on; a shared proxy across
  identities (the UI already warns, `en.ts` proxyShared).
- **Allowed silently:** common values repeating across profiles (MAY_REPEAT).

Advanced fields (custom UA, custom hardware, extra args) stay **out of the default form** and behind
an "Advanced" disclosure (already the case, frontend audit §B/§D); the engine treats them as
override inputs that must pass the reject-rules before they can be stored or hashed.

## Lifecycle semantics (make each explicit)

| Operation | Seed | Derived fields | Notes |
|-----------|------|----------------|-------|
| Create | new 64-bit CSPRNG | derived from template | never a client 32-bit seed (fixes F-007) |
| Edit (PATCH) | **preserved** | recomputed; revision bumps once per semantic change | matches current good behavior |
| Explicit regenerate | new | recomputed | monotonic revision (fixes F-017) |
| Duplicate | new (deliberate) | recomputed; proxy dropped | surface the semantic (F-019) |
| Import | new (deliberate) | recomputed | identity intentionally reset |
| Backup / restore | preserved | preserved (whole-DB) | assert seed on restore (test gap) |
| Browser upgrade | **preserved** | UA/CH/derived recomputed to new version, seed intact | the key coherence rule for upgrades |
| Free ↔ Pro switch | **preserved** | version-dependent fields recompute; **must not silently change identity** | degrade capabilities, keep the seed |

## Versioning & migration

- `schema_version` on the device model; `FINGERPRINT_REVISION` (currently 1,
  `fingerprints.py:13`) continues to gate hash-format changes.
- Any change to what enters `fingerprint_config_hash` (e.g. retiring hardware/GPU per F-006, or
  adding derived fields) requires a migration that recomputes hashes under an incremented revision,
  so existing profiles get a **one-time, explicit** re-baseline — never a silent identity change.
- Existing profiles must map onto a device template on first load (a best-fit assignment from their
  stored fields) without altering their seed.

## Free/Pro capability degradation

- The engine derives the same *intended* identity regardless of tier; the **binary capability gates**
  (F-004) decide which derived flags are actually emittable. When a flag can't be applied on the
  current binary, the engine records the surface as "not enforced on this binary" and diagnostics
  report it as such (never as applied) — consistent with the existing "report the limitation instead
  of fabricating a pass" stance (`PROFILE_FIELD_CAPABILITY_MATRIX.md:59`).

## Explicit non-goals

- No JS-level fingerprint spoofing (stays in the binary).
- No hundreds of randomly-combined personas — a curated, realistic template set only.
- No per-launch identity regeneration (breaks stability; excluded by the matrix).
