# 09 — Live Verification (real binary)

**Date:** 2026-07-24
**Binary:** `chromium-146.0.7680.177` (free tier), headless, driven via a CDP
**isolated world** (the first-party probe, `manager_backend/features/diagnostics/probe.py`).
**Method:** launched real profiles over the exact manager launch snapshot, evaluated the
probe collector, compared surfaces across seeds and across relaunch. This turns several
"Needs runtime verification" items from the static audit into **Confirmed** — and
**corrects one premature conclusion**.

Confidence here is **Confirmed (live)** unless noted. The free 146 binary was available in
`~/.cloakbrowser/`; the .NET port, a real SOCKS5 proxy, and Tier-2 (TLS/HTTP2/DNS) infra were
not, so those items remain open (see end).

## What was measured

Seeds probed: several distinct 64-bit seeds (e.g. `100/200/300/400`, `1111…/9999…`) plus a
same-seed relaunch, all with the **consistent** preset; a locale/timezone flag read-back; and a
Client-Hints read on an https page (secure context).

## Results

| Surface | Across different seeds | Same seed, relaunch | Classification (verified) |
|---|---|---|---|
| **WebGL / GPU renderer** | **VARIES** (seed100 → `RTX 3090`, seed200 → `RTX 3060`, 4/4 distinct) | **stable** | **seed-driven** — plausible per-seed NVIDIA models |
| **canvas** | **CONSTANT** | stable | **shared** under noise-off consistent preset |
| **audio** (real render hash) | **CONSTANT** (`338.4995…`) | stable | **shared** under noise-off consistent preset |
| **screen** | **CONSTANT** `1920×1080` | stable | **fleet-constant** |
| **hardwareConcurrency** | **CONSTANT** `8` | stable | **host-inherited / fleet-constant** |
| UA ↔ platform ↔ Client Hints | coherent | — | UA `Chrome/146` Windows; CH `platform=Windows, platformVersion=19.0.0 (Win11), x86/64, uaFullVersion=146.0.7680.177`, brands Chromium/Chrome 146 |
| `navigator.webdriver` | `false` | — | clean |
| native-API integrity | `[native code]` getter | — | intact (no JS shim) |

### Locale / timezone flag read-back (F-004)

Launched with `locale=de-DE`, `timezone=Europe/Berlin`:

```
navigator.language  = "de-DE"      navigator.languages = ["de-DE"]
Intl timeZone       = "Europe/Berlin"   Jan offset = -60 (CET, correct)
```

**The identity-critical geo flags apply on the free 146 binary — they are not silently dropped.**

## Corrections & confirmations to the static audit

1. **CORRECTION — GPU is not a host leak.** From a *single* run I saw a real-looking GPU
   (`RTX 3050`) and flagged a possible host-GPU passthrough. Multiple seeds show the renderer
   **varies per seed** and is stable per seed → the binary spoofs plausible per-seed GPUs. This is
   coherent seed-driven behavior, **not** the leak I implied. (Whether the *base model pool* is
   host-derived is a minor open question, but it is not static passthrough.) Lesson: never conclude
   a surface is host-inherited from one run — vary the seed.

2. **F-004 severity reduced (for 146).** `--fingerprint-locale` / `--lang` /
   `--fingerprint-timezone` demonstrably apply. The "silent flag drop" risk remains a concern only
   for *older* binaries or *untested* flags; for the bundled free build the geo flags work.

3. **F-010 confirmed.** `screen` is a fleet-constant `1920×1080` across all seeds; `devicePixelRatio`
   1, colorDepth 24. `hardwareConcurrency` is likewise fleet-constant (8). These do **not**
   differentiate profiles and are a mild fleet signal — but both are common real values (MAY_REPEAT).

4. **F-008 mechanism confirmed.** Client Hints are binary-derived and coherent with the automatic
   UA. Because CH come from the binary (not from any string), a **custom** UA still cannot move them
   — exactly the mismatch F-008 warns about; the Phase-1 "custom UA must declare Windows" reject is
   the right mitigation, and the CH-override remainder is still needed for custom UAs.

5. **NEW finding — canvas + audio are shared across profiles under the consistent preset.**
   With `--fingerprint-noise=false`, canvas and audio are deterministic (verified identical across
   different seeds, stable per seed). This is the **stability-vs-uniqueness tradeoff** made concrete:
   the surfaces that give a stable returning identity are the same ones that stop distinguishing your
   own profiles (and match other Plasma-on-same-GPU users). It is *by design*, not a bug — but it
   means canvas/audio must be treated as **MAY_REPEAT under the consistent preset**, which is now
   encoded in `analyze_separation(preset=...)` (`separation.py`): impossible-correlation only fires
   for canvas/audio under the noise-ON default preset; WebGL stays seed-driven under both.

## Probe refinements made (this pass)

- **Real audio fingerprint** — the collector now renders an `OfflineAudioContext` and hashes the
  output (was just `sampleRate`). Requires an async collector + `awaitPromise` evaluate.
- **Secure-context Client Hints** — `default_probe_page` accepts an optional `probe_url`; Client
  Hints (`userAgentData.getHighEntropyValues`) only populate on an https page, not `about:blank`.

## F-003 — WebRTC (partial live)

Enumerated real ICE candidates from the binary (isolated world, `stun.l.google.com`):

- **Baseline (no `--fingerprint-webrtc-ip`): 0 candidates** — no host/local IP exposed
  (partly a sandbox artifact: no reachable STUN/UDP here, so no `srflx` could form either way).
- **With `--fingerprint-webrtc-ip=203.0.113.99`: 2 candidates, both `203.0.113.99`** —
  the flag replaces **both** the `host` (local) and `srflx` (reflexive) candidate IPs with the
  supplied value.

**Verdict:** the masking primitive the manager uses in proxy mode **works at the candidate/
fingerprint layer** — a detection site enumerating ICE candidates sees only the supplied IP, not
the host's. **Caveat (unchanged):** this spoofs the *reported* IP; it does not route WebRTC UDP
through a TCP SOCKS5 proxy, so a media-path/packet observer could still see host-origin UDP. So
F-003 moves from "unknown" to **"candidate-layer masking verified; UDP-routing caveat still needs a
real proxy + packet capture."**

## Statistical separation — real 16-seed batch

16 distinct seeds through `analyze_separation(preset="consistent")`:

```
distinct webgl : 15/16   (one GPU collision — RTX 4050 shared by two seeds)
distinct canvas:  1/16    distinct audio: 1/16
distinct screen:  1/16    distinct cores: 1/16
```

This **caught a real bug in the analyzer**: it initially flagged the single GPU collision as an
"impossible correlation" and failed a *healthy* fleet. The GPU/WebGL renderer is **pool-selected**
(a finite set of NVIDIA models), so collisions across seeds are expected (birthday), not impossible.
Fixed: `separation.py` now treats WebGL/GPU as **MAY_REPEAT**; only canvas/audio under the noise-ON
default preset are "must differ per seed." (`test_webgl_pool_collision_is_not_a_failure`.)

Takeaway for the fleet: under the consistent preset the only per-profile-unique surfaces are the
**seed + config hash + GPU (mostly)**; canvas/audio/screen/cores are shared/common — consistent with
[F-021](02-findings.md).

## F-011 — partial local fix

Added a false-positive-free save-time check: a pinned `browser_version` **older than the bundled
free build** is rejected (`schemas.py::_pinned_version_older_than_bundled`, wired into create and
patch). Rejecting unresolvable *newer* pins still needs the cloud version list.

## Still open (need infra not present here)

- **F-003 remainder** — UDP-routing vs. reported-IP: needs a real remote SOCKS5 proxy + packet capture.
- **Tier-2** TLS/JA3/JA4 + HTTP/2 + DNS ownership — needs a controlled server/packet observer (a JS
  or public-service check is not authoritative).
- **F-011 remainder** — unresolvable *newer* pins: needs the cloud version list.
- **.NET port** live verification — no `dotnet` SDK in this environment (code parity done in Phase 3).
- A full **≥100-seed** statistical run (the 16-seed batch is representative; the analyzer scales).
