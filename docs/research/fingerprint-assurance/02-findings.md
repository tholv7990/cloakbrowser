# 02 — Findings (Audit Tasks 1–4)

Ordered by severity. Each finding uses the required format. IDs are stable (`F-0NN`) and referenced
from the other documents. "Confidence" is one of **Confirmed** (read in source),
**Strong inference** (follows from confirmed code + platform behavior), or
**Needs runtime verification** (depends on the closed binary or a live proxy).

Severity counts: **High 7 · Medium 8 · Low 5**. No finding is a *default-configuration* silent
host-IP leak on page traffic (that path fails closed — see F-013), which is why nothing is ranked
Critical on code evidence alone; the one candidate-Critical is F-003, gated on runtime proof.

---

## F-001 — [High] WebRTC "Disabled" mode does nothing

**Evidence**
- `manager_backend/features/runtime/launcher.py:291-297` — the only WebRTC handling; a flag is
  appended **only** when `webrtc_mode == "proxy"` and a proxy is present.
- `manager/frontend/src/features/profile-editor/steps.tsx:340-348` — the UI offers
  `Proxy / Direct / Disabled`.
- Wrapper: there is no WebRTC "off" flag anywhere (`cloakbrowser/browser.py`, wrapper audit §3).

**Failure scenario**
- Profile inputs: `location.webrtc_mode = "disabled"`.
- Launch mode: any (headed or diagnostic).
- Network: any.
- Observable wrong result: WebRTC stays fully enabled; `RTCPeerConnection` works and exposes
  whatever candidates the binary default produces. The user believes WebRTC is off.

**Risk:** false UI promise + potential host-IP leak.

**Fix**
- Component: `persistent_context_kwargs` (launcher.py) — handle all three modes explicitly.
- Runtime: for `disabled`, emit a real disable (a `--fingerprint-webrtc-*` off flag if the binary
  exposes one, else the Chromium `WebRTCIPHandlingPolicy=disable_non_proxied_udp` policy /
  pref, else disable via CDP `WebRTC` domain). If none is enforceable on the free binary,
  **remove "Disabled" from the UI** rather than offer a dead control.
- Migration: existing profiles with `disabled` keep the value; behavior only changes once enforced.
- Tests: `tests/manager/test_launcher.py` — add `test_webrtc_disabled_emits_disable_and_not_ip`
  (fails now: no flag emitted) and `test_webrtc_direct_emits_no_ip` (passes).

**Confidence:** Confirmed (wrapper emits nothing); the *effect of any disable flag* is
Needs runtime verification.

---

## F-002 — [High] Proxy-aligned geo silently falls back to the host timezone/locale

**Evidence**
- `manager_backend/features/proxies/service.py:267-279` (`_apply_proxy_geo`) — `snapshot["timezone"]`
  is set **only if** `result.timezone` is truthy; there is no country-based timezone fallback
  (locale has an `en-US` fallback, timezone has none).
- `cloakbrowser/browser.py:1260-1265` — `--fingerprint-timezone` is omitted when timezone is falsy.
- `launcher.py:90-95` — for `geo_mode="proxy"` the snapshot starts with `timezone=None`.

**Failure scenario**
- Profile inputs: `geo_mode="proxy"` (the default), any proxy assigned.
- Launch mode: normal.
- Network: proxy connects and the exit IP resolves, **but the GeoIP enrichment service is down /
  rate-limited / returns no timezone** (`lookup_geo` returns `{}`).
- Observable wrong result: the browser reports the **host** timezone (and host-derived locale)
  while all HTTP traffic egresses the proxy IP → a timezone/IP mismatch — exactly the
  "timezone spoofed" tell the design set out to avoid.

**Risk:** leak (timezone + locale) and coherence break, silent — no log, no warning, no launch abort.

**Fix**
- Component: `_apply_proxy_geo` + `build_proxy_preflight` (`proxies/service.py`).
- Runtime: derive timezone from exit **country** when the precise tz is missing (a
  country→representative-IANA-tz map, mirroring `_LOCALE_BY_COUNTRY`); if even the country is
  unknown for a `geo_mode="proxy"` profile, **fail the preflight** (`proxy_preflight_failed`)
  rather than launch with the host clock. Make the choice explicit and logged (safe reason code).
- Migration: none (runtime only).
- Tests: `tests/manager/test_runtime_manager.py` / proxy service tests — add
  `test_proxy_geo_missing_timezone_falls_back_to_country_not_host` (fails now) and
  `test_proxy_geo_unknown_country_blocks_launch` (fails now).

**Confidence:** Confirmed.

---

## F-003 — [High, candidate-Critical] WebRTC over a TCP SOCKS5 proxy cannot be routed; host-IP masking is binary-dependent

**Evidence**
- No SOCKS5 `UDP ASSOCIATE` support anywhere in `cloakbrowser/` or `manager_backend/` (grep: absent).
- `launcher.py:291-297` — masking is limited to the fingerprint flag `--fingerprint-webrtc-ip`,
  which the wrapper documents as spoofing the *reported* IP, not routing packets.

**Failure scenario**
- Profile inputs: `webrtc_mode="proxy"`, a `socks5://` proxy.
- Launch mode: any; a site that gathers ICE candidates (STUN).
- Network: WebRTC media/STUN uses UDP; a TCP SOCKS5 proxy cannot carry it, so the packets
  originate from the host's real UDP socket.
- Observable wrong result: if the binary spoofs the *reported* candidate but does not *suppress*
  the real host candidate, a site sees the true host IP alongside the spoofed one.

**Risk:** host public/local IP leak (defeats the entire proxy identity) — **if** the binary does
not suppress host candidates.

**Fix**
- Component: diagnostics (must *measure* this) + docs (must state the limitation).
- Runtime: add a first-party WebRTC probe (see [07](07-external-checker-policy.md)) that enumerates
  ICE candidates against a local STUN and asserts no host RFC1918 / real-public candidate appears.
  If the binary does not suppress host candidates, enforce the Chromium
  `WebRTCIPHandlingPolicy` (`disable_non_proxied_udp`) as a floor.
- Tests: differential harness case DT-WEBRTC (see [04](04-differential-test-design.md)) — must fail
  if any host candidate leaks under a SOCKS5 proxy.

**Confidence:** Needs runtime verification. This is the **#1 unknown** — it can only be settled by
a live WebRTC probe behind a real SOCKS5 proxy on the actual binary.

---

## F-004 — [High] Unsupported `--fingerprint-*` flags are silently dropped by an old/free binary but reported as active

**Evidence**
- Wrapper audit §"Failure-mode summary": Chromium silently ignores unknown switches (no error,
  no nonzero exit). `--fingerprint-locale`, `--fingerprint-noise`, `--fingerprint-storage-quota`
  are emitted with **no version gate** (`cloakbrowser/browser.py:170-172, 1266-1271`).
- Only three capabilities are version-gated (`config.py:314, 371, 411`); the rest are emitted blind.

**Failure scenario**
- Profile inputs: `fingerprint_preset="consistent"`, `geo_mode="manual"` with a locale.
- Launch mode: normal on a **stale free 146** binary that predates a given flag.
- Observable wrong result: the flag is dropped; noise stays on / locale unset, yet the manager and
  diagnostics report the setting as applied ("consistent preset", "locale = …").

**Risk:** false reporting — a setting the UI/diagnostics call active is silently inert.

**Fix**
- Component: `cloakbrowser/config.py` (`binary_supports_*`) + `launcher.py` reporting.
- Runtime: add version floors for the identity-critical `--fingerprint-*` flags, mirroring the
  three existing gates; when below floor, either don't claim the capability or add a post-launch
  read-back (see first-party probe, [07](07-external-checker-policy.md)) that verifies the surface
  actually changed. Diagnostics must report "applied" only after read-back, not on flag emission.
- Tests: `tests/manager/test_launcher.py` gate tests per flag; probe fixture asserting a
  "reported-but-not-applied" run is flagged.

**Confidence:** Confirmed (silent-drop mechanism); the *specific* per-flag floors are
Needs runtime verification against each binary.

---

## F-005 — [High] Geolocation and browser permissions are stored and shown but never applied

**Evidence**
- Grep of `manager_backend/features/runtime` for `permissions|geolocation` → **no matches**.
- `persistent_context_kwargs` (`launcher.py:279-311`) passes none of them.
- UI exposes 5 permission selects + geolocation mode + coordinates
  (`steps.tsx:358-378, 644-653`); the built-in "No-leak" template sets
  camera/mic/notifications = block (`profileTemplates.ts:24-33`) implying enforcement.

**Failure scenario**
- Profile inputs: "No-leak" template (camera/mic/notifications = block), or
  `geolocation_mode="manual"` with coordinates.
- Launch mode: normal.
- Observable wrong result: the browser uses **default** permission behavior (notifications/camera
  prompt as usual); manual geolocation coordinates are ignored; `geolocation_mode="block"` does not
  block. A user who set camera=block can still be prompted / permitted.

**Risk:** false privacy promise; coherence (a proxied profile that should report proxy-city
coordinates reports none or host-derived).

**Fix**
- Component: `persistent_context_kwargs` — pass Playwright context `permissions=[...]` and
  `geolocation={lat,long,accuracy}` (+ `--fingerprint`-side geolocation if the binary supports it).
- Runtime: map the 5 `ask/allow/block` selects to Playwright `grant_permissions` / default deny;
  wire `geolocation_mode="proxy"` to the exit-IP city centroid (reuse GeoIP), `manual` to the
  stored coords, `block` to no grant + permission denied.
- Migration: none (values already stored).
- Tests: `tests/manager/test_launcher.py` — `test_permissions_passed_to_context`,
  `test_manual_geolocation_coordinates_applied`, `test_geolocation_block_grants_nothing` (all fail now).

**Confidence:** Confirmed.

---

## F-006 — [High] Advanced behavior/window cluster is stored (two fields hashed) but never applied — phantom identity changes

**Evidence**
- Grep of `manager_backend/features/runtime` for
  `hardware_concurrency|gpu_vendor|gpu_mode|additional_args|humanize|clear_cache|ignore_https|color_scheme|restore_previous_tabs|download_directory`
  → **no matches**. None reach `persistent_context_kwargs` (`launcher.py:279-311`).
- `hardware_concurrency` and `gpu_vendor` **are** in the config hash
  (`fingerprints.py:33-40`), so editing them bumps `fingerprint_revision`
  (`service.py:406-412`) with no browser effect.
- `restore_previous_tabs` is ignored: `urls_to_open` always restores the last session
  (`launcher.py:260-262`).

**Failure scenario**
- Profile inputs: `hardware_concurrency=8` (custom) or `gpu_vendor="Google Inc. (AMD)"`, or
  `humanize_enabled=true`, or `restore_previous_tabs=false`, or `additional_args=[...]`.
- Launch mode: normal.
- Observable wrong result: `navigator.hardwareConcurrency` / GPU vendor are unchanged (still
  seed-derived) yet the profile's **revision incremented and config hash changed** — the system
  claims a new identity that the browser does not present. Humanize never activates; tabs restore
  even when the user turned restore off; extra Chromium args are dropped.

**Risk:** phantom identity (hash/revision diverge from reality) + dead features + false UI promises.

**Fix (two acceptable directions — pick per field)**
- **Wire it:** emit `--fingerprint-hardware-concurrency`, `--fingerprint-gpu-vendor` (behind a
  version gate per F-004); pass `humanize=` to `cloakbrowser.launch_persistent_context`; honor
  `restore_previous_tabs` in `urls_to_open`; append validated `additional_args`; apply
  `color_scheme`, `ignore_https_errors`, download dir, clear-cache.
- **Or retire it:** remove the field from the form/schema **and** from the config hash
  (for hardware_concurrency/gpu_vendor) so the hash never asserts an unbacked change.
- Never leave a field hashed-but-not-applied.
- Migration: if hardware/gpu are retired from the hash, add a migration that recomputes
  `fingerprint_config_hash` for existing profiles under `FINGERPRINT_REVISION += 1`.
- Tests: `test_launcher.py` per newly-wired flag; `test_schemas.py` update for hash membership;
  `test_profiles_api.py::test_hardware_override_recalculates_hash_not_seed` must be reconciled with
  whichever direction is chosen (it currently asserts the hash changes for an unapplied field).

**Confidence:** Confirmed.

---

## F-007 — [Medium] The create wizard supplies a 32-bit `Math.random()` seed, bypassing the backend's 64-bit CSPRNG

**Evidence**
- `manager/frontend/src/schemas/profile.ts:151` — wizard default seed is `String(random 0..2^32)`
  via `Math.random()`; the "Generate" button uses the same range (`steps.tsx:414-436`).
- Backend strong path: `fingerprints.py:75-80` (`secrets.randbits(64)`) is used only when
  `fingerprint_seed is None` (`service.py:126`) — but the wizard always sends a value.
- The No-leak template correctly strips the seed (`profileTemplates.ts:62-63`) so the backend
  64-bit path runs; the single-profile wizard does not.

**Failure scenario**
- Profile inputs: create a profile through the advanced wizard (not the No-leak template).
- Observable wrong result: the seed comes from a non-cryptographic 32-bit PRNG. Entropy drops from
  2^64 to 2^32; birthday-collision reaches ~50% near ~77k profiles (vs astronomically safe at
  2^64), and `Math.random()` is predictable, so seeds may be guessable/correlated.

**Risk:** weakened uniqueness/unpredictability; more 409 conflicts at scale; cross-profile
correlation of seed-derived surfaces if the PRNG stream is inferable.

**Fix**
- Component: `manager/frontend/src/schemas/profile.ts` + the wizard.
- Runtime: **omit the seed from the create payload by default** (let the backend 64-bit CSPRNG
  generate it), and if a client-side seed is offered, use `crypto.getRandomValues` over a full
  64-bit range.
- Tests: `manager/frontend/src/features/profiles/NewProfileModal.test.tsx` — assert the create
  payload omits `fingerprint_seed` (or that it is 64-bit); backend already covers uniqueness.

**Confidence:** Confirmed.

---

## F-008 — [High] Custom User-Agent has no coherence validation and cannot reconcile with Client Hints

**Evidence**
- `schemas.py:137, 184-187` — `custom_user_agent` accepts any string ≥ 20 chars; the only check is
  length + mode consistency.
- `launcher.py:305` passes it straight to the CDP `user_agent` kwarg.
- Client Hints have **no flag** and are entirely binary/seed-driven (wrapper audit §4), so they are
  not derived from the custom UA.

**Failure scenario**
- Profile inputs: `user_agent_mode="custom"`, `custom_user_agent="Mozilla/5.0 (Macintosh; …) Chrome/120…"`.
- Launch mode: normal.
- Observable wrong result: `navigator.userAgent` says macOS/Chrome 120 while `navigator.platform`,
  `Sec-CH-UA-Platform`, `userAgentData`, fonts and the actual engine say Windows/Chrome 146 — a
  hard, trivially detectable UA-vs-CH-vs-platform contradiction.

**Risk:** coherence break (cross-layer), the single most common antidetect failure.

**Fix**
- Component: `schemas.py` validation + a coherence validator (see
  [06-coherence-engine-design.md](06-coherence-engine-design.md)).
- Runtime: parse the custom UA and **reject** (or warn hard) when its platform/major version
  contradicts the selected binary/platform; when accepted, also override Client Hints via CDP
  `Network.setUserAgentOverride` with a matching `userAgentMetadata` so CH and UA agree.
- Tests: `test_schemas.py` — `test_custom_ua_conflicting_platform_rejected`,
  `test_custom_ua_version_mismatch_warns`; launcher test asserting CH metadata is set alongside UA.

**Confidence:** Confirmed (no reconciliation exists); the exact observed CH values are
Needs runtime verification.

---

## F-009 — [Medium] Coarse country→locale map produces locale/timezone/region mismatches

**Evidence**
- `manager_backend/features/proxies/service.py:257-279` — `_LOCALE_BY_COUNTRY` maps one language
  per country; unmapped countries fall back to `en-US`.

**Failure scenario**
- Profile inputs: `geo_mode="proxy"`, proxy exits in Switzerland (unmapped → `en-US`), or Canada
  (always `en-CA`, never `fr-CA`), or Belgium (always `nl-BE`, never `fr-BE`), or Indonesia/Egypt/
  Argentina (unmapped → `en-US`).
- Observable wrong result: `navigator.language = en-US` with a `Europe/Zurich` timezone and a Swiss
  IP — an implausible combination for the region; or a French-Canadian exit reporting `en-CA`.

**Risk:** coherence (locale ↔ region ↔ timezone) inconsistency; weak but real fingerprint signal.

**Fix**
- Component: `_LOCALE_BY_COUNTRY` and derivation.
- Runtime: expand to the plausible dominant locale per country and, where multiple are common,
  either pick the majority or key off exit region; fall back to the country's real primary language,
  not `en-US`. Consider deriving locale from the GeoIP languages field when available.
- Tests: proxy service tests — `test_locale_map_covers_common_exit_countries`,
  `test_unmapped_country_does_not_default_to_en_us_against_non_english_tz`.

**Confidence:** Confirmed.

---

## F-010 — [Medium] Screen resolution is likely constant (1920×1080) across all consistent-preset profiles

**Evidence**
- `launcher.py:265-270` comment: "The consistent fingerprint preset spoofs a 1920×1080 screen" and
  the manager sizes the window to match because the free 146 binary lacks the 148+ screen-clamp.
- `PROFILE_FIELD_CAPABILITY_MATRIX.md:27` excludes independent screen spoofing.

**Failure scenario**
- Profile inputs: any two consistent-preset profiles (the default).
- Observable wrong result: both report `screen.width/height = 1920×1080` (and likely identical DPR /
  color depth). If this is 100% constant, it is a fleet-wide correlation signal and does not vary
  with the device persona.

**Risk:** cross-profile correlation (fleet signal) + implausible uniformity. Note: 1920×1080 is a
*common* real resolution, so **MAY_REPEAT** — the problem is only if it is *invariant across the
entire fleet* and never tracks the persona.

**Fix**
- Component: coherence engine (device model, [06](06-coherence-engine-design.md)) + binary capability.
- Runtime: if the binary can spoof screen dimensions per seed (a 148+ capability), derive screen
  from the device persona so it varies plausibly; if not, document the limitation explicitly and
  ensure the window size is still coherent with the (fixed) screen.
- Tests: statistical separation suite ([05](05-stability-and-separation.md)) measuring the
  per-component duplicate rate of screen dimensions across ≥100 profiles.

**Confidence:** Needs runtime verification (the actual reported `screen.*` values live in the binary).

---

## F-011 — [Medium] Arbitrary pinned `browser_version` can desync the UA/engine

**Evidence**
- `schemas.py:178-181` — pinned mode accepts any string matching `^[0-9]+(\.[0-9]+){3,4}$`.
- `launcher.py:81-85` passes it as `browser_version`; per the Quantum model the wrapper resolves it
  to a downloadable binary.

**Failure scenario**
- Profile inputs: `browser_version_mode="pinned"`, `browser_version="999.0.0.0"` (nonexistent) or a
  version whose binary is unavailable to this tier.
- Observable wrong result: depending on resolution, either a launch failure or (worst case) a UA
  claiming a version the actual engine does not match.

**Risk:** coherence (UA vs engine) or operational failure.

**Fix**
- Component: `schemas.py` validation + version resolution.
- Runtime: validate the pinned version against the set the current tier can actually resolve
  (bundled + server latest); reject unknown versions at save time with a safe error code rather than
  failing at launch.
- Tests: `test_profiles_api.py` — `test_pin_unresolvable_version_rejected`.

**Confidence:** Strong inference (resolution behavior is in the wrapper/server).

---

## F-012 — [Medium] `socks5h` scheme may cause a silent DIRECT + DNS leak

**Evidence**
- `cloakbrowser` parser accepts `socks5h` (`parser.py` scheme set) and preserves it into
  `--proxy-server` (proxy audit §4c). Chromium's `--proxy-server` does not recognize `socks5h`.

**Failure scenario**
- Profile inputs: a proxy stored with scheme `socks5h`.
- Network: Chromium may treat the scheme as invalid and fall back to DIRECT.
- Observable wrong result: host IP + local DNS used for all traffic, silently.

**Risk:** silent proxy fallback → host-IP + DNS leak.

**Fix**
- Component: proxy URL building (`proxies/service.py:213-231` / wrapper `_resolve_proxy_config`).
- Runtime: coerce `socks5h` → `socks5` (Chromium does remote DNS for `socks5` anyway) before
  building the launch URL, or reject `socks5h` at proxy save time.
- Tests: proxy service — `test_socks5h_coerced_to_socks5_for_launch`.

**Confidence:** Strong inference / Needs runtime verification (Chromium's exact reaction to the
scheme on this binary).

---

## F-013 — [Medium] No runtime proxy health monitor / kill-switch after launch

**Evidence**
- `worker.py:109-147` — after launch the worker only watches for process exit / stop; there is no
  proxy liveness monitoring. The 60s preflight cache (`service.py:282`) can even admit a proxy that
  died within the last minute.

**Failure scenario**
- Profile inputs: any proxied profile.
- Network: the proxy dies mid-session.
- Observable wrong result: page traffic fails closed (Chromium errors `ERR_PROXY_CONNECTION_FAILED`,
  no DIRECT fallback — good), **but** WebRTC/UDP exposure (F-003) persists and nothing stops the
  browser or warns the user.

**Risk:** operational failure + prolonged leak window (via F-003).

**Fix**
- Component: `worker.py` (add an optional periodic proxy health check) + UI surfacing.
- Runtime: on repeated proxy failure, transition to a `degraded`/`stopping` state with a safe reason
  code; do not silently continue.
- Tests: `test_runtime_manager.py` — `test_proxy_death_midsession_is_surfaced`.

**Confidence:** Confirmed (absence of a monitor); page-traffic fail-closed is Strong inference.

---

## F-014 — [Medium] Proxy credentials appear inline in the child Chrome process argv

**Evidence**
- Proxy audit §1: for SOCKS5 (always) and inline-auth HTTP, creds are baked into
  `--proxy-server=scheme://user:pass@host` (`cloakbrowser/browser.py:1547,1553,1564,1568`).
- The manager itself reads other processes' cmdlines (`launcher.py:323-330, 398-408`), proving the
  local readability.

**Failure scenario**
- Profile inputs: any authenticated proxy.
- Observable wrong result: any local process (or a low-priv user) can read the proxy username and
  password from the Chrome command line, even though the DB stores only a keyring ref.

**Risk:** local plaintext credential exposure (not a network leak; a local threat-model gap).

**Fix**
- Component: proxy launch path.
- Runtime: prefer Playwright's CDP proxy-auth interceptor (already the HTTP-no-inline path,
  `browser.py:1570-1573`) over inline argv creds wherever the binary supports it; document the
  residual exposure for SOCKS5 where inline is unavoidable.
- Tests: N/A at unit level (argv content); document in threat model ([03](03-threat-model.md)).

**Confidence:** Confirmed.

---

## F-015 — [High] A custom window size larger than the spoofed screen creates an impossible geometry

**Evidence**
- `launcher.py:273-276` (`_window_size_arg`) honors custom width up to 7680 / height up to 4320
  (`schemas.py:66-68`), but the consistent preset spoofs a fixed 1920×1080 screen and the free 146
  binary lacks the screen-clamp (`launcher.py:265-270`).

**Failure scenario**
- Profile inputs: `window.mode="custom"`, `width=2560, height=1440` (a normal monitor), consistent
  preset, free binary.
- Observable wrong result: `window.outerWidth/innerWidth (2560) > screen.width (1920)` — physically
  impossible; detectors flag `outerWidth > screen.availWidth`.

**Risk:** coherence break (window ↔ screen), trivially detectable.

**Fix**
- Component: `schemas.py` (validate custom window ≤ spoofed screen for the active preset/binary) and
  the coherence engine (derive window from the device persona's screen).
- Runtime: clamp/reject custom sizes exceeding the spoofed screen; when a binary can spoof screen
  per persona, size both together.
- Tests: `test_schemas.py` — `test_custom_window_exceeding_spoofed_screen_rejected`;
  `test_launcher.py` — window size never exceeds the reported screen.

**Confidence:** Strong inference (window logic Confirmed; the fixed 1920×1080 screen value is
Needs runtime verification).

---

## F-016 — [Low] The wrapper's own default seed is a 5-digit `randint(10000,99999)` (footgun if the manager seed is bypassed)

**Evidence**
- `cloakbrowser/config.py:60,65` — default `--fingerprint` is `random.randint(10000,99999)`.
- In the manager path the 64-bit seed wins via arg dedup (extra_args beat stealth defaults,
  `browser.py:1236,1252-1257`), so this only bites when the wrapper/`cloakserve` is used directly.

**Failure scenario:** direct wrapper or `cloakserve` use without an explicit `--fingerprint` →
seed space collapses to ~90k → high collision.

**Risk:** cross-profile correlation for non-manager callers.

**Fix:** widen the wrapper default to a 64-bit CSPRNG value; keep manager precedence. Test:
`js/`/Python wrapper unit asserting the default seed range.

**Confidence:** Confirmed.

---

## F-017 — [Low] `regenerate_fingerprint` resets revision to 1 instead of incrementing

**Evidence**
- `service.py:450-458` — sets `fingerprint_revision = identity.revision` (== `FINGERPRINT_REVISION`,
  i.e. 1), unlike `update_profile` which increments (`service.py:411`).

**Risk:** a cache keyed on `(profile_id, revision)` could collide after a regenerate that lands back
on revision 1. Minor.

**Fix:** monotonic revision (never decrease) even on regenerate, or key caches on the config hash
(which is unique). Test: `test_profiles_api.py::test_regenerate_does_not_lower_revision`.

**Confidence:** Confirmed.

---

## F-018 — [Low] Duplicated `--fingerprint` responsibility relies on dedup precedence

**Evidence**
- Manager emits `--fingerprint=<seed>` (`launcher.py:284`) and the wrapper also emits its own
  (`config.py:65`); correctness depends on `build_args` letting extra_args win
  (`browser.py:1236,1252-1257`).

**Risk:** a future change to dedup precedence would silently swap the stable seed for the wrapper's
random one. Latent fragility.

**Fix:** have the manager pass the seed through the wrapper's first-class `fingerprint=`/seed
parameter rather than as a raw arg, or add a guard/assert + comment. Test: existing
`test_runtime_manager.py:114` already asserts the injected `--fingerprint` wins; add a regression
comment referencing precedence.

**Confidence:** Confirmed.

---

## F-019 — [Low/Medium] Duplicate mints a new identity silently

**Evidence**
- `service.py:424-447` — `duplicate_profile` builds a `ProfileCreate` without a seed → new 64-bit
  seed, and drops the proxy (documented, `service.py:442-444`).

**Failure scenario:** a user duplicates a "known-good, warmed-up" profile expecting the same
identity; they get a fresh one (and no proxy).

**Risk:** operational surprise, not a leak. The default is *safer* (no accidental twins), but it is
implicit.

**Fix:** surface the semantic in the duplicate confirmation copy ("creates a new identity; assign a
proxy"), and — if there is demand — offer an explicit "clone identity" variant that is clearly
labelled as producing a linkable twin. Test: FE dialog copy test.

**Confidence:** Confirmed.

---

## F-020 — [Low] Diagnostics coverage gaps + orphaned UI affordances

**Evidence**
- Built-in checkers are only `direct_google_control / pixelscan / iphey / cloudflare / google_search`
  (`models.py:283`); no BrowserScan/BrowserLeaks/CreepJS/AmIUnique.
- Orphaned i18n keys imply a "Fingerprint check" kind with no `DiagnosticKind` or UI backing
  (`en.ts:249`, frontend audit §H).
- `diag.artifactUnavailable` copy contradicts the rendered artifact links (frontend audit §H.7).

**Risk:** no first-party fingerprint probe exists (external checkers only); minor UI inconsistency.

**Fix:** build the first-party local probe ([07](07-external-checker-policy.md)); remove or wire the
orphaned strings. Test: covered by the probe plan.

**Confidence:** Confirmed.

---

## Verified strengths (stated for balance — a skeptical audit still credits what holds)

These are **Confirmed** and should not be "fixed":

- **Seed core:** 64-bit CSPRNG (`fingerprints.py:77`) + DB `unique=True` (`models.py:199`) + retry
  (`fingerprints.py:75-80`); stable across PATCH, explicit-only regeneration, fresh on
  duplicate/import — all covered by tests (`test_profiles_api.py:34,82,130,344,448`,
  `test_database.py:106`).
- **Config-hash discipline:** bumps once per semantic identity change; operational fields don't move
  it (`test_profiles_api.py:448`, `test_schemas.py:89`).
- **Secrets:** proxy creds in OS keyring not DB, write-only in schema, never logged
  (`proxies/service.py:59-85, 220-223`); snapshot proxy_url stays in worker memory.
- **Fail-closed proxy:** dead proxy with testing on aborts the launch, no DIRECT fallback for page
  traffic (`worker.py:148-165`, `service.py:341-346`).
- **Isolation:** per-profile `user-data` dir → cookies/storage/extensions/cache isolated by design
  (`launcher.py:592-599`).
- **Honest UI:** explicitly anti-promises OS/screen spoofing and Win10/11 personas, labels
  diagnostics as observations, never solves CAPTCHAs (`en.ts` notes, frontend audit §B/§C/§G).
- **Portability safety:** export strips identity; backups are DB-only, exclude profile dirs
  (`test_profile_portability.py:145`, `local-data-ownership.md:30-33`).
