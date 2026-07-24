# 01 — Current Control Matrix (Audit Task 1)

Every fingerprint-relevant value, traced from the form to the browser, classified by who actually
controls it **at runtime today**. This is a snapshot of the *implemented* behavior, not the
*documented intent* — where they differ, the row says so and links to a finding in
[02-findings.md](02-findings.md).

## Classification legend

| Class | Meaning |
|-------|---------|
| **PLASMA_CONTROLLED** | Manager sets it and it demonstrably reaches the browser (flag or context kwarg). |
| **CLOAK_ENGINE_CONTROLLED** | Owned by the closed binary / seed; not independently settable from a flag. |
| **PROXY_DERIVED** | Value is computed from the proxy exit IP at preflight. |
| **HOST_INHERITED** | Follows the host machine (by design or by omission). |
| **UNVERIFIED** | A flag/kwarg is emitted, but nothing confirms the binary honored it. |
| **UI_ONLY_OR_DEAD** | Present in the UI/schema with no runtime wiring. |
| **STORED_BUT_NOT_APPLIED** | Persisted (and sometimes hashed) but never sent to the launch. |
| **APPLIED_BUT_NOT_STORED** | Sent at launch but not persisted (recomputed each time). |

Legend for "In hash?": whether the field is part of `fingerprint_config_hash`
(`manager_backend/fingerprints.py:33-40, 55-66`). A field that is in the hash but not applied
produces a **phantom identity change** (revision bumps, browser unchanged) — see F-006.

## A. Identity core — applied and verified by tests

| Field | Type | Default | Class | In hash? | Reaches browser as | Evidence |
|-------|------|---------|-------|----------|--------------------|----------|
| `fingerprint_seed` | decimal str (u64) | 64-bit CSPRNG (backend) / **32-bit `Math.random()` (wizard)** | PLASMA_CONTROLLED | yes | `--fingerprint=<seed>` | `fingerprints.py:75-80`, `launcher.py:284`; wizard default `profile.ts:151` → **F-007** |
| `fingerprint_preset` | `default`\|`consistent` | `consistent` | PLASMA_CONTROLLED / UNVERIFIED | yes | kwarg → `--fingerprint-noise=false` (+ storage-quota) in "consistent" | `schemas.py:133`, `launcher.py:300`, `browser.py:170-172`; silent-drop risk **F-004** |
| `browser_version_mode` / `browser_version` | enum / version str | `installed` / null | PLASMA_CONTROLLED | yes | selects the downloaded binary (pinned) else bundled `get_chromium_version()` | `launcher.py:81-85`; UA/engine coherence when pinned is correct (binary swap), arbitrary pin risk **F-011** |
| `fingerprint_revision` / `fingerprint_config_hash` | int / sha256 | 1 / computed | PLASMA_CONTROLLED (internal) | n/a | not sent to browser; identity bookkeeping | `service.py:406-412`, `fingerprints.py:43-72` |
| proxy assignment (`proxy_id`) | uuid | null | PLASMA_CONTROLLED | no | `--proxy-server=<url>` (creds inline) | `service.py:234-239`, `launcher.py:304`; argv exposure **F-014** |
| extensions (enabled) | paths | none | PLASMA_CONTROLLED | no | `--load-extension` / `--disable-extensions-except` | `launcher.py:37-59`, `browser.py:1277-1280` |
| `startup_urls` / tab restore | urls | [] | PLASMA_CONTROLLED | no | new pages at launch | `launcher.py:260-262, 615-627` |

## B. Location / network identity

| Field | Default | Class | Reaches browser as | Evidence / finding |
|-------|---------|-------|--------------------|--------------------|
| `location.geo_mode` = `manual` | — | PLASMA_CONTROLLED | `locale`/`timezone` kwargs pinned | `launcher.py:93-94` |
| `location.geo_mode` = `proxy` (default) | — | PROXY_DERIVED → **HOST_INHERITED on failure** | `timezone` from exit-IP GeoIP; locale from country map | `service.py:267-279`; **F-002 (silent host-tz leak)** |
| `location.geo_mode` = `system` | — | HOST_INHERITED | nothing pinned; browser follows host | `launcher.py:90-95` |
| `location.locale` (proxy) | `en-US` fallback | PROXY_DERIVED (coarse) | `--lang` + `--fingerprint-locale` | `service.py:257-279`; **F-009 (coarse map)** |
| `location.timezone` (proxy) | — | PROXY_DERIVED | `--fingerprint-timezone` | `service.py:276-277`, `browser.py:1260-1265` |
| `location.webrtc_mode` = `proxy` (default) + proxy | — | PLASMA_CONTROLLED / PROXY_DERIVED | `--fingerprint-webrtc-ip=<exit\|auto>` | `launcher.py:291-297`; UDP reality **F-003** |
| `location.webrtc_mode` = `direct` | — | HOST_INHERITED (intended) | no flag | `launcher.py:291-297` |
| `location.webrtc_mode` = `disabled` | — | **UI_ONLY_OR_DEAD** | no flag emitted; WebRTC not disabled | `launcher.py:291-297`; **F-001** |
| `location.geolocation_mode` (`ask`/`proxy`/`manual`/`block`) | `ask` | **STORED_BUT_NOT_APPLIED** | never passed | absent from `persistent_context_kwargs` `launcher.py:279-311`; **F-005** |
| `location.latitude/longitude/accuracy` | null | **STORED_BUT_NOT_APPLIED** | never passed | same; **F-005** |
| `test_proxy_before_launch` | true | PLASMA_CONTROLLED | gates preflight liveness test | `service.py:322-346` |

## C. Browser / OS persona (mostly engine-owned)

| Field | Default | Class | Notes | Evidence |
|-------|---------|-------|-------|----------|
| `user_agent_mode`=`automatic` | default | CLOAK_ENGINE_CONTROLLED | UA string derived by binary/seed | `browser.py` (no UA flag), wrapper report |
| `custom_user_agent` (`custom`) | null | PLASMA_CONTROLLED / **coherence-unsafe** | CDP `user_agent` override; **Client Hints stay engine-driven → mismatch** | `launcher.py:305`; **F-008** |
| navigator.platform / UA platform token | `windows` | CLOAK_ENGINE_CONTROLLED (from host) | `--fingerprint-platform` derived from host OS | `config.py:70-76`; Windows-only by design |
| Client Hints (`Sec-CH-UA*`, `userAgentData`) | — | CLOAK_ENGINE_CONTROLLED | **no flag exists**; entirely binary | wrapper report §4 |
| Windows fonts | — | HOST_INHERITED | binary uses host Windows font set | wrapper report §4 |
| TLS/JA3/JA4, HTTP/2 | — | CLOAK_ENGINE_CONTROLLED | inside binary; unobservable from repo | wrapper report §4 |

## D. Hardware / rendering surfaces

| Field | Default | Class | In hash? | Notes | Evidence / finding |
|-------|---------|-------|----------|-------|--------------------|
| `behavior.hardware_concurrency_mode`=`automatic` | default | CLOAK_ENGINE_CONTROLLED | no | seed-derived cores | — |
| `behavior.hardware_concurrency` (`custom`) | null | **STORED_BUT_NOT_APPLIED** | **yes** | phantom identity: hash bumps, no flag emitted | absent in `launcher.py:279-311`; **F-006** |
| `behavior.gpu_mode`=`automatic` | default | CLOAK_ENGINE_CONTROLLED | no | seed-derived GPU | — |
| `behavior.gpu_vendor` (`custom_vendor`) | null | **STORED_BUT_NOT_APPLIED** | **yes** | phantom identity | absent in launcher; **F-006** |
| Canvas / WebGL / Audio noise | — | CLOAK_ENGINE_CONTROLLED | no | seed + `--fingerprint-noise` toggle only | `browser.py:170` |
| GPU renderer, device memory | — | CLOAK_ENGINE_CONTROLLED | no | not independently settable (matrix excludes) | `PROFILE_FIELD_CAPABILITY_MATRIX.md:31-32` |
| screen resolution / DPR / color depth | — | CLOAK_ENGINE_CONTROLLED (likely fixed 1920×1080) | no | window sized to match; constant-across-fleet risk | `launcher.py:265-270`; **F-010, F-015** |

## E. Window / behavior (largely dead wiring)

| Field | Default | Class | Evidence / finding |
|-------|---------|-------|--------------------|
| `window.mode`/`width`/`height` | maximized | PLASMA_CONTROLLED | `--window-size`; custom>screen contradiction **F-015** |
| `window.color_scheme` | system | **STORED_BUT_NOT_APPLIED** | absent in launcher; **F-006** |
| `behavior.humanize_enabled/preset` | false/default | **STORED_BUT_NOT_APPLIED** | humanize kwarg never passed; **F-006** |
| `behavior.permissions` ×5 (cam/mic/notif/geo/clipboard) | block/ask | **STORED_BUT_NOT_APPLIED** | never passed; No-leak template implies enforcement; **F-005** |
| `behavior.clear_cache_before_launch` | false | **STORED_BUT_NOT_APPLIED** | no cache-clear in launcher; **F-006** |
| `behavior.restore_previous_tabs` | true | **STORED_BUT_NOT_APPLIED (dead toggle)** | `urls_to_open` always restores; ignores flag `launcher.py:260-262`; **F-006** |
| `behavior.ignore_https_errors` | false | **STORED_BUT_NOT_APPLIED** | never passed; **F-006** |
| `behavior.download_directory_mode`/`custom_download_directory` | profile | **STORED_BUT_NOT_APPLIED** | never passed; **F-006** |
| `behavior.additional_args` | [] | **STORED_BUT_NOT_APPLIED** | validated/rejected manager-owned, then not appended to args; **F-006** |

## Summary counts

- **PLASMA_CONTROLLED (working):** seed, preset, browser_version, proxy, extensions, startup_urls,
  manual locale/timezone, window size, WebRTC-proxy IP — the identity spine is wired.
- **CLOAK_ENGINE_CONTROLLED:** UA(auto), Client Hints, platform, fonts, Canvas/WebGL/Audio, GPU,
  screen, TLS/HTTP2 — correct to defer to the binary, but **UNVERIFIED** from this repo.
- **STORED_BUT_NOT_APPLIED / UI_ONLY_OR_DEAD (13 fields):** all of section E plus geolocation,
  WebRTC "disabled", custom hardware/GPU. This is the largest correctness gap. See **F-005, F-006**.
- **APPLIED_BUT_NOT_STORED:** none material (window default size is recomputed, but that is a
  constant, not identity).

The critical structural takeaway: **the config hash covers two fields (`hardware_concurrency`,
`gpu_vendor`) that are never applied**, so the hash can assert an identity change the browser never
makes. Either wire them or remove them from both the form and the hash (see F-006).
