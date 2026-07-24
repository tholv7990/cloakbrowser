# 04 — Differential Test Design (Audit Task 5)

Goal: compare CloakBrowser against **genuine Chrome of the matching version**, inspecting
**behavior and structure**, not only values. A value match (`hardwareConcurrency === 8`) is weak; a
structural match (same property descriptors, same prototype chain, same `toString`, same exception
type) is what separates a real engine from a patched one.

## Comparison cells

| Cell | What it is | Purpose |
|------|-----------|---------|
| A | Genuine Chrome @ bundled Chromium version | ground truth for structure |
| B | CloakBrowser Free (146) | the shipped free identity |
| C | CloakBrowser Pro (latest) | the paid identity |
| D | Manual visible browsing | human baseline (no automation tells) |
| E | Playwright-controlled | the manager's actual launch path |
| F | Direct network | no-proxy baseline |
| G | HTTP proxy | credentialed HTTP path |
| H | SOCKS5 proxy | the WebRTC/UDP stress path (F-003) |

Run the collector in every meaningful combination (e.g. B×E×H = free + Playwright + SOCKS5). The
**A vs B/C** axis catches structural divergence; **D vs E** catches automation tells; **F vs G vs H**
catches proxy/leak issues.

## What the collector inspects (structure-first)

For every surface, capture not just the value but its **shape**:

- **Property descriptors:** `Object.getOwnPropertyDescriptor(navigator,'webdriver')` etc. — enumerable/
  configurable/getter presence. Patched props often differ here.
- **Prototype chains:** `navigator.__proto__` walk; is `hardwareConcurrency` an own prop or on the
  prototype (real Chrome: prototype getter)?
- **`Function.prototype.toString`:** stringify native getters (`navigator.hardwareConcurrency`'s
  getter, `WebGLRenderingContext.getParameter`). Must read `function get x() { [native code] }`, not
  a JS shim. A `toString` that reveals a hook is an instant tell.
- **Errors and exception types:** call APIs in illegal ways and compare the thrown error class and
  message (e.g. `getContext('webgl',{failIfMajorPerformanceCaveat:...})` edge cases, `TypeError` vs
  `DOMException`).
- **API availability:** presence/order of keys on `navigator`, `window`, `screen`, `Intl`.

Surfaces to enumerate per cell:

- UA + all `Sec-CH-UA*` request headers + `navigator.userAgentData.getHighEntropyValues([...])`
- `navigator` (platform, languages, hardwareConcurrency, deviceMemory, plugins, mimeTypes, webdriver,
  vendor, product, oscpu)
- Canvas 2D + **OffscreenCanvas** (hash + text metrics)
- WebGL + WebGL2 (`getParameter` vendor/renderer/unmasked, extensions list, precision formats, max
  texture sizes) + **WebGPU** adapter (`requestAdapter().info`)
- AudioContext (fingerprint + `baseLatency`, `sampleRate`)
- Fonts / text metrics (`measureText` across a probe set) + ClientRects (`getClientRects` geometry)
- `screen` (width/height/avail/colorDepth/pixelDepth) + viewport + `devicePixelRatio`
- `Intl.DateTimeFormat().resolvedOptions()` (timeZone, locale) + `Date` offset
- Geolocation availability + permission state
- WebRTC ICE candidates (host/srflx/relay) against a **local STUN**
- Media devices (`enumerateDevices` labels/ids) + `speechSynthesis.getVoices()`
- `permissions.query` for the managed set + `navigator.plugins`
- Automation: `navigator.webdriver`, CDP tells, `window.chrome` shape, `Notification.permission`

## Verdict model

Per surface, emit one of `identical | structurally-equal | value-differs | structurally-differs |
unsupported | not-comparable`. **Structural divergence from genuine Chrome (A) is the failure**, not
a value difference — different profiles are *supposed* to differ in values. This mirrors the
existing repo stance (`PROFILE_FIELD_CAPABILITY_MATRIX.md:58-59`,
`plans/2026-07-21-profile-fingerprint-verification.md`), which this design extends rather than
replaces.

## Where JavaScript is NOT enough (be honest about the boundary)

The task is explicit: do not claim TLS validation if the collector runs only in JS.

- **TLS / JA3 / JA4:** invisible to JS. Requires a **controlled TLS-terminating server** (or a
  packet observer) that records the ClientHello and computes JA3/JA4, compared against genuine Chrome
  hitting the same endpoint. Belongs in a first-party test server, not the in-page probe.
- **HTTP/2 (Akamai) fingerprint:** invisible to JS. Requires the same controlled server to record
  the SETTINGS/WINDOW_UPDATE/HEADERS frame order and pseudo-header order.
- **WebRTC true UDP origin (F-003):** the in-page probe sees candidates, but proving the *packets*
  originate from the proxy (not the host) needs a **packet-level observer** or a STUN server that
  logs the source IP of the binding request. This is the decisive test for F-003.
- **DNS ownership:** proving remote vs local resolution needs a **controlled authoritative DNS**
  that logs the resolver IP, or packet capture.

Recommendation: two tiers. **Tier 1 (in-page JS probe)** covers everything observable in the page —
cheap, deterministic, CI-friendly (see [07](07-external-checker-policy.md)). **Tier 2 (controlled
server / packet observer)** covers TLS, HTTP/2, WebRTC-UDP origin, and DNS — a separate, gated,
manually-run harness (never a hard CI dependency). Do not let Tier 1 assert Tier 2 claims.

## Deterministic fixtures for CI

The in-page probe must run against a **local static fixture page** (no public sites) so CI is
deterministic and offline, matching the existing diagnostics test approach (fixture pages + injected
runner adapters, live tests behind `CLOAK_LIVE_DIAGNOSTICS=1`,
`specs/2026-07-22-manager-fingerprint-diagnostics-design.md`). The A-vs-B structural comparison uses
a **checked-in golden** captured from genuine Chrome of the bundled version; regenerate the golden on
each Chromium bump (tie it to F-004's version gates).

## Minimum CI subset vs full manual matrix

- **CI (fast, offline):** B×E×F in-page probe vs golden A; asserts structural equality on
  navigator/Canvas/WebGL/Audio/screen/Intl and no automation tells.
- **Manual/gated (live):** the full A–H matrix incl. Tier 2, run before a release or a binary bump.
  CAPTCHA frequency is recorded as telemetry only, never a pass/fail (see [08](08-release-gates.md)).
