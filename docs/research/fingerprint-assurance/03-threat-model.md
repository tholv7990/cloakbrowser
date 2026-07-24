# 03 — Threat Model & Leak Surfaces (Audit Task 4)

## Adversary and goal

The adversary is a **website / anti-bot service** that fingerprints the browser and cross-checks
declared identity against observed reality (IP ↔ timezone ↔ locale ↔ WebRTC ↔ TLS ↔ Client Hints).
Its win condition is *any* internal contradiction or *any* host value leaking through the proxy
persona. A secondary adversary is a **local low-privilege process** on the same Windows host
(relevant only to F-014).

The defender's goal is not invisibility; it is a **coherent, stable, host-free identity** that
survives cross-layer checks and proxy conditions. "Passing Pixelscan" is explicitly not the bar.

## Leak-surface register

Each surface: what could leak, whether the current code prevents it, and the residual risk.
"Binary" = the closed CloakBrowser engine owns the outcome and it is **unverifiable from this repo**.

| # | Surface | Host value that could leak | Current handling | Residual risk | Finding |
|---|---------|----------------------------|------------------|---------------|---------|
| 1 | **Host public IP (HTTP)** | real egress IP | `--proxy-server`; dead proxy aborts (test on) | fail-closed for page traffic | F-013 |
| 2 | **Host public IP (WebRTC/STUN, UDP)** | real IP via ICE | `--fingerprint-webrtc-ip` (reported only); no UDP routing over SOCKS5 | **unknown — binary must suppress host candidate** | **F-003** |
| 3 | **Host local IP (WebRTC mDNS/host candidate)** | 192.168.x / mDNS | none at wrapper | Binary-dependent | F-003 |
| 4 | **DNS resolver** | host DNS / ISP | `socks5://` = remote DNS (Chromium) | `socks5h` may fall back to DIRECT+local DNS | F-012 |
| 5 | **IPv6 path** | real v6 egress | none explicit; exit IP usually v4 | v6 host candidate / dual-stack leak | F-003 |
| 6 | **Timezone** | host TZ | proxy-derived; **host fallback on GeoIP miss** | silent host-TZ leak | **F-002** |
| 7 | **Locale / Accept-Language** | host locale | proxy-country map; en-US fallback | coarse/incoherent | F-002, F-009 |
| 8 | **Geolocation (JS API)** | host / none | **not applied at all** | manual coords ignored, block not enforced | F-005 |
| 9 | **Real GPU vendor/renderer** | host GPU strings | seed/binary-derived (not host, by design) | Binary-dependent; custom GPU vendor is dead | F-006 (Binary) |
| 10 | **Host fonts** | installed Windows fonts | binary uses host font set (Windows-only) | Binary; host font *set* is the persona | see §Host-inheritance |
| 11 | **Screen / monitor layout** | real resolution/DPR | window sized to spoofed 1920×1080 | likely fleet-constant; custom window > screen | F-010, F-015 |
| 12 | **CPU cores / device memory** | real values | seed-derived; custom is dead | custom HW concurrency not applied | F-006 |
| 13 | **Media-device IDs** | host camera/mic IDs | not managed | Binary-dependent | see §Unmanaged |
| 14 | **Speech voices** | host TTS voices | not managed | Binary-dependent | see §Unmanaged |
| 15 | **Automation / CDP / webdriver** | `navigator.webdriver`, CDP tells | `--enable-automation` + swiftshader suppressed; CDP used for stealth reads | residual CDP artifacts unverified | §Automation |
| 16 | **Cookies / storage between profiles** | cross-profile linkage | per-profile `user-data` dir | isolated (Confirmed) | §Isolation |
| 17 | **Extensions between profiles** | shared extension state | per-profile load; shared read-only source dirs | isolated | §Isolation |
| 18 | **Cache / service workers / IndexedDB** | cross-profile / host | per-profile dir | isolated | §Isolation |
| 19 | **History / HSTS state** | prior-visit linkage | per-profile dir | isolated | §Isolation |
| 20 | **Profile paths / usernames** | host username in paths | paths kept out of diagnostics; redact required | must redact in any probe output | F-020, [07] |
| 21 | **Crash-recovery / last-session** | prior tabs | bounded + validated restore | restore toggle is dead (still restores) | F-006 |
| 22 | **Remote-debugging port** | open CDP port | loopback binding (per specs) | verify no `0.0.0.0` bind | §Automation |

## Proxy failure modes (Audit Task 4, focused)

Confirmation of the central requirement — *a proxy failure must never silently fall back to the
direct network*:

- **Dead proxy, testing ON (default):** preflight `tester.run_fast` fails →
  `ManagerError("proxy_preflight_failed")` → worker transitions to `crashed`, **browser never
  launches** (`proxies/service.py:341-346`, `worker.py:148-165`). No traffic at all. **Confirmed.**
- **Dead proxy, testing OFF or within 60s cache:** the browser launches with `--proxy-server` set.
  Chromium with an explicit proxy does **not** fall back to DIRECT for page traffic — it errors
  `ERR_PROXY_CONNECTION_FAILED`. **No host-IP leak for page traffic. Strong inference** (Chromium
  behavior, not enforced by repo code). Residual: WebRTC/UDP (F-003) is a separate path.
- **Proxy dies mid-session:** page traffic fails closed; **no monitor** stops the browser or warns
  (F-013). Leak window for F-003 persists until the user closes it.
- **`socks5h` scheme:** may be rejected by Chromium → **possible** silent DIRECT + local DNS leak
  (F-012). Needs runtime verification.
- **Rotating residential proxy:** the exit IP (hence WebRTC IP + timezone) is captured at preflight;
  if it rotates after launch, the reported values go stale. Unavoidable at launch time, but a
  mid-session monitor (F-013) could re-derive.

## Host inheritance (by design vs by omission)

- **By design (correct for a Windows-only product):** `navigator.platform=windows`, the Windows
  font set, and the real display geometry on newer binaries are *supposed* to mirror the host — a
  cross-OS persona would itself be a tell. The capability matrix and UI say so explicitly and
  honestly (`PROFILE_FIELD_CAPABILITY_MATRIX.md:12,27`, `en.ts` platform/window notes).
- **By omission (bugs):** host timezone/locale under a failed proxy geo (F-002), and unenforced
  geolocation/permissions defaulting to host behavior (F-005). These are leaks, not design.

## Automation / CDP posture

- Positives (Confirmed): the wrapper strips `--enable-automation` and the SwiftShader tell via
  `IGNORE_DEFAULT_ARGS` (`config.py:47`), and does DOM stealth reads through CDP Isolated Worlds
  rather than `page.evaluate` (per `human/` design, CLAUDE.md). `navigator.webdriver` should be
  false.
- Unverified: residual CDP artifacts, `Runtime.enable` tells, and whether the remote-debugging
  endpoint binds loopback-only in every launch path (specs claim loopback; must be asserted).
  These belong in the differential harness ([04](04-differential-test-design.md), DT-AUTO).

## Unmanaged surfaces (media devices, speech voices)

Media-device enumeration and `speechSynthesis` voices are not touched by the manager and rely
entirely on the binary. They are common real leak vectors (host device labels / voice lists) and
must be **measured** by the first-party probe before any claim is made about them. No code evidence
either way — **Needs runtime verification**.

## Isolation (Confirmed strength)

Each profile launches with its own `profile_dir/user-data` (`launcher.py:592-599`). Cookies,
localStorage, IndexedDB, service workers, cache, history, HSTS and extension state therefore live in
separate directories and cannot cross profiles. Extensions are loaded read-only from shared source
dirs, which does not share per-profile state. This is the strongest part of the leak posture.
