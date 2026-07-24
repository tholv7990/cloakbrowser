# 08 — Release Gates (Audit Task 10)

Two tiers: **hard blockers** (a release must not ship if any is true) and **non-blocking telemetry**
(recorded, trended, alerted on — never auto-fails a build). The split matters because a checker's
mood swing or a common Canvas hash is signal, not a defect.

## Hard release blockers

A release is blocked if **any** of these is observed by the first-party probe
([07](07-external-checker-policy.md)) or the differential harness ([04](04-differential-test-design.md)):

| Gate | Condition that blocks | Backing finding | How it is measured |
|------|-----------------------|-----------------|--------------------|
| G1 Direct host-IP leak | any request egresses the host IP when a proxy is assigned | F-003, F-012, F-013 | live proxy run; page + WebRTC egress observed at a controlled server |
| G2 DNS / IPv6 leak | DNS resolved locally, or a host IPv6 candidate appears, under a proxy | F-012, F-003 | controlled DNS + STUN observer |
| G3 WebRTC public-IP contradiction | ICE exposes a host public/local IP that differs from the proxy IP | F-001, F-003 | WebRTC probe vs local STUN under SOCKS5 |
| G4 Silent proxy fallback | a dead/misconfigured proxy launches with traffic on the direct network | F-012, F-013 | kill the proxy pre/mid launch; assert fail-closed |
| G5 UA / kernel / Client-Hint mismatch | `navigator.userAgent`, `userAgentData`, `Sec-CH-UA*`, `navigator.platform`, and the real engine version disagree | F-008, F-011 | in-page probe cross-check |
| G6 Unstable profile seed | the same profile yields a different seed/identity across restart, manager restart, or backup-restore | test gaps #2/#4 in [05] | stability suite |
| G7 Profile storage crossover | any cookie/storage/cache/history bleeds between profiles | isolation ([03]) | two-profile isolation test |
| G8 Impossible device model | window > screen, cross-OS UA, or a hardware/GPU/screen combo no real device has | F-015, F-008, coherence validator ([06]) | validator + probe |
| G9 New automation marker | `navigator.webdriver` true, a CDP tell, or an E-vs-D divergence not present in genuine Chrome | automation ([03]) | differential DT-AUTO |
| G10 Substantial divergence from genuine Chrome | a **structural** difference (descriptor/prototype/`toString`/exception type) from matched genuine Chrome on a core surface | [04] | A-vs-B structural compare |
| G11 Unsupported setting reported as active | any setting the UI/diagnostics call "applied" that the binary silently dropped, or a field hashed but not applied | F-004, F-005, F-006 | probe read-back after launch; config-hash-vs-applied audit |

G11 is the gate that directly indicts the current build: today `webrtc_mode="disabled"`,
geolocation, permissions, custom hardware/GPU (hashed!), humanize, restore-tabs, color-scheme,
download-dir, and extra-args are all "reported as configured" but not applied (F-005/F-006). Under
G11 the current build **would not pass** until those are either wired or removed from the
UI/hash — which is the point.

## Non-blocking telemetry (record, trend, alert — never auto-fail)

| Signal | Why it is telemetry, not a gate |
|--------|--------------------------------|
| Uniqueness score | high uniqueness can be *bad* (too rare) or fine; not a pass/fail |
| CAPTCHA occurrence | frequency correlates with many factors (IP reputation, behavior); not proof of a fingerprint defect; never solved |
| Proxy ASN reputation | a "datacenter"/"flagged" ASN is a proxy-quality issue, not a browser defect |
| One external checker changing its verdict | third-party UI/heuristic drift; corroborate across ≥2 before acting |
| Common Canvas/WebGL hashes | shared *common* values are expected (MAY_REPEAT); only fleet-wide 100% uniformity or seed-decorrelation is a defect ([05]) |
| Checker timeout / error | network flake; recorded as `timeout`/`error`, not a fingerprint result |

## Gate wiring (how these become enforceable)

- G6, G7, G8, G11 are **CI-enforceable now** with backend/frontend tests + the in-page probe
  (offline, deterministic). These should land first.
- G1–G5, G9, G10 need the **live/gated harness** (real proxy + controlled server), run before a
  release or a binary bump behind `CLOAK_LIVE_DIAGNOSTICS=1`; they must be green in the pre-release
  run, not on every commit.
- Each gate names the test that proves it in the implementation plan
  ([../../superpowers/plans/2026-07-24-fingerprint-assurance.md](../../superpowers/plans/2026-07-24-fingerprint-assurance.md)).

## The overarching rule

Do **not** optimize toward green badges. A build can be green on Pixelscan and still fail G1/G5/G11.
The gates test *coherence, stability, isolation, and honesty of reporting* — the badge is, at most,
one non-blocking telemetry input.
