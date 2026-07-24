# Fingerprint Assurance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax. **TDD is mandatory:** write the failing test, prove it fails, implement,
> prove it passes. Do **not** implement during the audit that produced this plan. Commit frequently
> (one focused commit per task) but **only when the repo owner explicitly asks** — this audit did not
> commit anything.

**Goal:** Close the gaps in [docs/research/fingerprint-assurance/02-findings.md](../../research/fingerprint-assurance/02-findings.md)
so profiles are leak-safe, internally coherent, stable, isolated, Chrome-like, and safe under proxies
and automation — without weakening the binary verification chain and without changing the free/dev
default behavior.

**Architecture:** Fix wiring first (make the UI honest), then leaks, then entropy/lifecycle, then the
coherence engine and the measurement harness that enforces the release gates. Fingerprint spoofing
stays in the closed binary; Plasma owns coherence, validation, and honest reporting.

**Tech stack:** Python 3.13, FastAPI, SQLAlchemy, pytest; React + TypeScript, Vitest, tsc, Vite.

## Validation commands (run from repo root unless noted)

- Backend focused: `python -m pytest tests/manager/<file>.py -q`
- Backend full (fast): `python -m pytest tests/manager -q -m "not slow"` — baseline today: **715 passed, 4 skipped, 1 deselected**
- Frontend (from `manager/frontend/`): `npm run typecheck` · `npm run test -- --run` · `npm run build` — baseline today: typecheck clean, **111 passed**, build OK
- OpenAPI: `python -m manager_backend.export_openapi` then `python -m pytest tests/manager/test_openapi_static.py -q`

## Global constraints

- Never expose secrets (proxy creds, cookies, tokens, license, seeds-in-logs). Fixed safe error codes only.
- Never weaken `cloakbrowser/download.py` Ed25519→SHA256 verification. Never modify the binary or the `.rar`.
- All new enforcement stays **flag-gated OFF or capability-gated** so the free/dev build is unchanged unless a binary supports it.
- Every task keeps the full suites green before it is considered done.

---

## Phase 1 — Make the UI honest (CI-enforceable; gate G11)

### Task 1: WebRTC "disabled" and "direct" are enforced or removed (F-001)

**Files:**
- Modify: `manager_backend/features/runtime/launcher.py`
- Test: `tests/manager/test_launcher.py`

- [ ] Add failing tests: `test_webrtc_disabled_emits_disable_not_ip`, `test_webrtc_direct_emits_no_ip`, `test_webrtc_proxy_still_emits_exit_ip`.
- [ ] Run `python -m pytest tests/manager/test_launcher.py -q`; confirm the disabled/direct tests fail.
- [ ] Implement: handle all three `webrtc_mode` values in `persistent_context_kwargs`. For `disabled`, emit the binary's WebRTC-off flag if `cloakbrowser.config.binary_supports_*` reports it, else set Chromium `WebRTCIPHandlingPolicy=disable_non_proxied_udp`; if neither is enforceable, remove "Disabled" from the schema/UI in Task 12 instead.
- [ ] Run the focused test; confirm all pass. Then `python -m pytest tests/manager -q -m "not slow"`.

### Task 2: Geolocation and permissions reach the launch (F-005)

**Files:**
- Modify: `manager_backend/features/runtime/launcher.py`
- Test: `tests/manager/test_launcher.py`, `tests/manager/test_runtime_manager.py`

- [ ] Add failing tests: `test_permissions_passed_to_context`, `test_manual_geolocation_coordinates_applied`, `test_geolocation_block_grants_nothing`, `test_geolocation_proxy_uses_exit_city`.
- [ ] Run focused tests; confirm failures (fields currently never reach `persistent_context_kwargs`).
- [ ] Implement: map `behavior.permissions` (5 keys) to Playwright `permissions=`/deny, and `location.geolocation_mode` + coords to `geolocation=`; `proxy` mode uses the exit-IP city centroid (reuse GeoIP from the preflight result).
- [ ] Run focused + full fast suite; confirm green.

### Task 3: Retire or wire the dead behavior/window cluster; fix the hash (F-006)

**Files:**
- Modify: `manager_backend/features/runtime/launcher.py`, `manager_backend/fingerprints.py`
- Modify (if retiring): `manager_backend/features/profiles/schemas.py`, `manager/frontend/src/features/profile-editor/steps.tsx`
- Migration (if hash membership changes): `manager_backend/migrations/versions/` (new revision)
- Test: `tests/manager/test_launcher.py`, `tests/manager/test_schemas.py`, `tests/manager/test_profiles_api.py`

- [ ] Decide per field (wire vs retire) using [06-coherence-engine-design.md](../../research/fingerprint-assurance/06-coherence-engine-design.md); record the decision in the task PR description.
- [ ] Add failing tests for each **wired** field (`test_hardware_concurrency_flag_emitted`, `test_gpu_vendor_flag_emitted`, `test_humanize_passed`, `test_restore_previous_tabs_false_skips_restore`, `test_additional_args_appended`, `test_color_scheme_applied`) and, for each **retired** field, a test that it no longer enters `fingerprint_config_hash`.
- [ ] Run focused tests; confirm failures.
- [ ] Implement the chosen direction. If `hardware_concurrency`/`gpu_vendor` are retired from the hash, add an Alembic migration that recomputes `fingerprint_config_hash` under `FINGERPRINT_REVISION += 1` (a one-time explicit re-baseline; seeds untouched).
- [ ] Reconcile `tests/manager/test_profiles_api.py::test_hardware_override_recalculates_hash_not_seed` with the chosen direction.
- [ ] Run full fast suite; regenerate OpenAPI if schemas changed (`python -m manager_backend.export_openapi`) and run `tests/manager/test_openapi_static.py`.

### Task 4: Custom window size cannot exceed the spoofed screen (F-015)

**Files:**
- Modify: `manager_backend/features/profiles/schemas.py`
- Test: `tests/manager/test_schemas.py`

- [ ] Add failing test `test_custom_window_exceeding_spoofed_screen_rejected` (e.g. 2560×1440 rejected while the consistent preset spoofs 1920×1080 on the free binary).
- [ ] Run `python -m pytest tests/manager/test_schemas.py -q`; confirm failure.
- [ ] Implement a validator that clamps/rejects custom window dimensions above the active preset's spoofed screen (parameterized by binary capability).
- [ ] Run focused + full fast suite; regenerate + verify OpenAPI.

### Task 5: Custom UA coherence validation + Client-Hint override (F-008)

**Files:**
- Modify: `manager_backend/features/profiles/schemas.py`, `manager_backend/features/runtime/launcher.py`
- Test: `tests/manager/test_schemas.py`, `tests/manager/test_launcher.py`

- [ ] Add failing tests: `test_custom_ua_conflicting_platform_rejected` (a macOS UA on a Windows profile), `test_custom_ua_sets_matching_client_hints`.
- [ ] Run focused tests; confirm failures.
- [ ] Implement: reject a custom UA whose platform/major version contradicts the selected binary/platform; when accepted, also set `userAgentMetadata` via CDP `Network.setUserAgentOverride` so Client Hints match the UA.
- [ ] Run focused + full fast suite.

---

## Phase 2 — Proxy & geo leaks (mix of CI + gated; gates G1–G5)

### Task 6: Proxy geo never falls back to the host (F-002, F-009)

**Files:**
- Modify: `manager_backend/features/proxies/service.py`
- Test: `tests/manager/test_proxy_quick_test.py`, `tests/manager/test_runtime_manager.py`

- [ ] Add failing tests: `test_proxy_geo_missing_timezone_falls_back_to_country_not_host`, `test_proxy_geo_unknown_country_blocks_launch`, `test_locale_map_covers_common_exit_countries`.
- [ ] Run focused tests; confirm failures.
- [ ] Implement: a country→representative-IANA-timezone map used when the precise tz is missing; for `geo_mode="proxy"` with an unknown country, raise `proxy_preflight_failed` (safe code) instead of leaving tz `None`; expand `_LOCALE_BY_COUNTRY` and stop defaulting non-English regions to `en-US`.
- [ ] Run focused + full fast suite.

### Task 7: `socks5h` cannot cause a silent direct/DNS leak (F-012)

**Files:**
- Modify: `manager_backend/features/proxies/service.py`
- Test: `tests/manager/test_proxy_api.py`

- [ ] Add failing test `test_socks5h_coerced_to_socks5_for_launch_url`.
- [ ] Run `python -m pytest tests/manager/test_proxy_api.py -q`; confirm failure.
- [ ] Implement: coerce `socks5h`→`socks5` when building the launch URL (Chromium does remote DNS for `socks5`). Keep `socks5h` valid for storage.
- [ ] Run focused + full fast suite.

### Task 8: Mid-session proxy health surfacing (F-013)

**Files:**
- Modify: `manager_backend/features/runtime/worker.py`
- Test: `tests/manager/test_runtime_manager.py`

- [ ] Add failing test `test_proxy_death_midsession_is_surfaced` (worker transitions to a degraded state with a safe reason code on repeated proxy failure).
- [ ] Run focused test; confirm failure.
- [ ] Implement an optional, bounded periodic proxy health check that surfaces failure without exposing creds; default interval conservative, gated by the existing `test_proxy_before_launch`/settings.
- [ ] Run focused + full fast suite.

---

## Phase 3 — Seed entropy & lifecycle hygiene (CI-enforceable; gate G6)

### Task 9: Wizard uses the backend 64-bit CSPRNG seed (F-007)

**Files:**
- Modify: `manager/frontend/src/schemas/profile.ts`, `manager/frontend/src/features/profile-editor/steps.tsx`
- Test: `manager/frontend/src/features/profiles/NewProfileModal.test.tsx`

- [ ] Add failing test asserting the create payload omits `fingerprint_seed` by default (letting the backend generate it) or, if a client seed is offered, that it uses `crypto.getRandomValues` over a full 64-bit range.
- [ ] Run `npm run test -- --run` (from `manager/frontend`); confirm failure.
- [ ] Implement: default the wizard to omit the seed; if the "Generate" button stays, use `crypto.getRandomValues`.
- [ ] Run `npm run typecheck && npm run test -- --run && npm run build`; confirm green.

### Task 10: Lifecycle hardening (F-016, F-017, F-018, F-019)

**Files:**
- Modify: `manager_backend/features/profiles/service.py`, `cloakbrowser/config.py` (+ `js/src/config.ts`, `dotnet/` per the three-ports rule for the wrapper default seed only)
- Test: `tests/manager/test_profiles_api.py`, wrapper unit tests

- [ ] Add failing tests: `test_regenerate_does_not_lower_revision` (monotonic revision), `test_concurrent_auto_create_seeds_do_not_collide` (threaded race → both succeed with distinct seeds or one gets a clean retry, never a shared seed), and a wrapper test asserting the default `--fingerprint` seed is 64-bit.
- [ ] Run focused tests; confirm failures.
- [ ] Implement: monotonic revision on regenerate; widen the wrapper default seed to a 64-bit CSPRNG (all three ports); add a guard/comment where the manager seed overrides the wrapper seed (F-018); surface the duplicate "new identity" semantic in the FE confirm copy (F-019).
- [ ] Run backend full fast suite + wrapper tests (`pytest` for cloakbrowser, `npm run test` in `js/`, `dotnet test` in `dotnet/`).

---

## Phase 4 — First-party probe & coherence engine (enables gates G8, G10, G11)

### Task 11: First-party local fingerprint probe (F-020, backbone for F-003/F-004)

**Files:**
- New: `manager_backend/features/diagnostics/probe.py`
- New: a local fixture page under `manager_backend/features/diagnostics/` (confirm exact location against the existing runner's fixture handling before creating)
- Modify: `manager_backend/features/diagnostics/runner.py`, `schemas.py`, `manager_backend/models.py` (add the `fingerprint_probe` diagnostic kind to the existing CHECK constraint via migration)
- Modify: `manager/frontend/src/features/diagnostics/` (wire the orphaned `diag.kind.fingerprintCheck` string)
- Migration: `manager_backend/migrations/versions/` (new revision extending the `diagnostic_runs.kind` constraint)
- Test: `tests/manager/test_fingerprint_probe.py` (new), `tests/manager/test_openapi_static.py`

- [ ] Add failing tests against a deterministic fixture: probe returns normalized JSON with separate `raw` and `verdict` blocks; redacts local paths/username; never includes cookies/history; asserts UA-vs-CH coherence and window-vs-screen coherence verdicts.
- [ ] Run `python -m pytest tests/manager/test_fingerprint_probe.py -q`; confirm failures.
- [ ] Implement the probe per [07-external-checker-policy.md](../../research/fingerprint-assurance/07-external-checker-policy.md) Part B, reusing the exact launch snapshot (as `test_diagnostic_runner.py:282` does).
- [ ] Add the migration + regenerate OpenAPI; run `tests/manager/test_openapi_static.py`.
- [ ] Run backend full fast + frontend suites.

### Task 12: Binary-capability read-back so nothing is falsely reported active (F-004)

**Files:**
- Modify: `cloakbrowser/config.py` (`binary_supports_*` for identity-critical `--fingerprint-*` flags; +`js/`/`dotnet/` per the three-ports rule)
- Modify: `manager_backend/features/runtime/launcher.py` (report "applied" only after probe read-back)
- Test: `tests/manager/test_launcher.py`, `tests/manager/test_fingerprint_probe.py`

- [ ] Add failing tests: a stale-binary fixture where `--fingerprint-locale`/`-noise` are dropped is reported as "not enforced", not "applied".
- [ ] Run focused tests; confirm failures.
- [ ] Implement version floors mirroring the three existing gates; diagnostics/report layer consults the probe read-back before claiming a surface is applied.
- [ ] Run focused + full fast suite; run wrapper ports' tests.

### Task 13: Canonical device model + coherence validator (F-008/F-010/F-011/F-015 consolidation)

**Files:**
- New: `manager_backend/features/fingerprints/` device-model + validator modules (create the package; confirm no name clash with the existing top-level `manager_backend/fingerprints.py`, and either extend that file or import it)
- Modify: `manager_backend/features/profiles/schemas.py`, `service.py`
- Migration: `manager_backend/migrations/versions/` (map existing profiles to a device template without changing seeds)
- Test: `tests/manager/test_coherence.py` (new), `tests/manager/test_profiles_api.py`

- [ ] Add failing tests: reject impossible models (window>screen, cross-OS UA, impossible hardware/GPU/screen combo, unresolvable pinned version); warn on unusual-but-possible; allow common repeats.
- [ ] Run `python -m pytest tests/manager/test_coherence.py -q`; confirm failures.
- [ ] Implement the curated Windows device templates + derivation + validation per [06-coherence-engine-design.md](../../research/fingerprint-assurance/06-coherence-engine-design.md). Existing profiles map to a best-fit template on migration; seeds untouched; browser-upgrade path recomputes derived fields while preserving the seed.
- [ ] Run full fast suite + regenerate/verify OpenAPI.

---

## Phase 5 — Differential & separation harnesses (gates G6–G10)

### Task 14: In-page differential probe vs genuine-Chrome golden (Tier 1, CI)

**Files:**
- New: `tests/manager/test_differential_probe.py`
- New: a checked-in golden captured from genuine Chrome of the bundled version (regenerated on each Chromium bump)
- Test infra: reuse the probe fixture from Task 11

- [ ] Add failing tests asserting structural equality (descriptors, prototype chain, `toString`, exception types) between the probe output and the golden on navigator/Canvas/WebGL/Audio/screen/Intl, and no automation tells (E-vs-D).
- [ ] Run `python -m pytest tests/manager/test_differential_probe.py -q`; confirm failures.
- [ ] Implement per [04-differential-test-design.md](../../research/fingerprint-assurance/04-differential-test-design.md) Tier 1 (offline, deterministic).
- [ ] Run backend full fast suite.

### Task 15: Statistical separation suite (≥100 CI, 1,000 gated)

**Files:**
- New: `tests/manager/test_separation.py`

- [ ] Add a failing test that generates 100 profiles and asserts: 0 duplicate seeds/config-hashes, per-component duplicate rates within bounds ([05-stability-and-separation.md](../../research/fingerprint-assurance/05-stability-and-separation.md)), and no impossible correlations; add a `slow`-marked 1,000-profile statistical variant.
- [ ] Run `python -m pytest tests/manager/test_separation.py -q`; confirm failure.
- [ ] Implement; keep the 1,000-profile suite behind the `slow` marker so `-m "not slow"` stays fast.
- [ ] Run `python -m pytest tests/manager -q -m "not slow"`; confirm green.

### Task 16: Gated live harness (Tier 2 — TLS/HTTP2/WebRTC-UDP/DNS)

**Files:**
- New: `tests/manager/e2e/` live harness entries (confirm the existing e2e layout before adding)
- Docs: link each gate to its test

- [ ] Add live, `CLOAK_LIVE_DIAGNOSTICS=1`-gated checks for G1–G5, G9, G10 using a controlled TLS/HTTP2 server + STUN/DNS observer per [04](../../research/fingerprint-assurance/04-differential-test-design.md) "Where JavaScript is NOT enough".
- [ ] Verify these are excluded from the default `-m "not slow"` run and do not become a hard CI dependency.
- [ ] Document the pre-release run procedure.

---

## Phase 6 — Wire the release gates

### Task 17: Enforce the gate matrix

**Files:**
- Modify: CI config / test selection; `docs/research/fingerprint-assurance/08-release-gates.md` (link tests)

- [ ] Map each gate G1–G11 to the concrete test(s) that prove it (from Tasks 1–16).
- [ ] Make G6, G7, G8, G11 hard CI failures; make G1–G5, G9, G10 required in the gated pre-release run.
- [ ] Confirm CAPTCHA occurrence, uniqueness score, ASN reputation, and single-checker verdict drift are recorded as **telemetry only** (never auto-fail).
- [ ] Final: `python -m pytest tests/manager -q -m "not slow"`, `cd manager/frontend && npm run typecheck && npm run test -- --run && npm run build`, `python -m manager_backend.export_openapi && python -m pytest tests/manager/test_openapi_static.py -q` — all green.

---

## Suggested review boundaries (independently reviewable)

- PR 1: Phase 1 (honesty fixes) — self-contained, high value, CI-provable.
- PR 2: Phase 2 (proxy/geo leaks).
- PR 3: Phase 3 (seed/lifecycle).
- PR 4: Task 11 (probe) — the measurement backbone.
- PR 5: Tasks 12–13 (capability read-back + coherence engine).
- PR 6: Phase 5 (harnesses).
- PR 7: Phase 6 (gates).

Each PR keeps both suites green and regenerates OpenAPI when schemas move. Do not commit or push
until the repo owner asks.
