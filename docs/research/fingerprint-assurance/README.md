# Fingerprint Assurance Audit

**Date:** 2026-07-24
**Scope:** Plasma / CloakBrowser Profile Manager fingerprint architecture — Windows desktop.
**Status:** Audit + design. No production code was changed by this audit (docs only).
**Repo state at audit:** `origin/main` @ `dc2389e`, local working tree carries only the unrelated
Settings-license-view work and this `docs/` addition.

## Why this exists

The objective is not green badges on Pixelscan. It is a browser identity that is **leak-safe,
internally coherent, stable across sessions, isolated between profiles, structurally Chrome-like,
and safe under proxies and automation**. A profile that passes a checker but reports a host
timezone under a proxy, or whose "Disabled WebRTC" toggle does nothing, is a failure regardless
of the badge.

## What was audited (evidence base)

All findings are traced through the real launch path:

```
frontend form (manager/frontend/src/features/profile-editor/steps.tsx)
  → API schema (manager_backend/features/profiles/schemas.py)
  → service + identity (manager_backend/features/profiles/service.py, fingerprints.py)
  → DB model (manager_backend/models.py)
  → launch snapshot (manager_backend/features/runtime/launcher.py: profile_launch_snapshot)
  → proxy preflight + geo (manager_backend/features/proxies/service.py: build_proxy_preflight)
  → launch kwargs (launcher.py: persistent_context_kwargs)
  → wrapper flag assembly (cloakbrowser/browser.py: build_args)
  → closed CloakBrowser binary  ← NOT inspectable; effects are INFERRED, never asserted
  → diagnostics (manager_backend/features/diagnostics/)
```

The closed binary is a **hard evidence boundary**. Everything that happens *inside* it
(Canvas/WebGL/Audio noise values, Client Hints, TLS/JA3/JA4, HTTP/2, actual WebRTC candidate
suppression, screen spoofing) cannot be confirmed from this repository and is labelled
**Needs runtime verification** wherever it matters.

## Evidence confidence levels

Every claim in these documents is tagged:

- **Confirmed** — read directly in this repository's source (file:line given).
- **Strong inference** — follows necessarily from confirmed code + documented platform behavior
  (e.g. Chromium's handling of `--proxy-server`), but no test exercises it here.
- **Needs runtime verification** — depends on the closed binary or a live network/proxy and
  must be proven with a differential run before it can be trusted.

Vendor claims (README marketing, competitor blogs) are treated as **hypotheses**, never facts.
Where a repo doc already states a careful position, this audit cites it rather than re-deriving.

## Document index

| File | Audit tasks | Contents |
|------|-------------|----------|
| [01-current-control-matrix.md](01-current-control-matrix.md) | 1 | Every fingerprint field, classified (PLASMA_CONTROLLED / CLOAK_ENGINE_CONTROLLED / PROXY_DERIVED / HOST_INHERITED / UNVERIFIED / UI_ONLY_OR_DEAD / STORED_BUT_NOT_APPLIED / APPLIED_BUT_NOT_STORED). |
| [02-findings.md](02-findings.md) | 1–4 | All findings in the required format (Evidence / Failure scenario / Risk / Fix / Confidence), ranked. |
| [03-threat-model.md](03-threat-model.md) | 4 | Leak surfaces, proxy failure modes, host-inheritance, automation signals, isolation. |
| [04-differential-test-design.md](04-differential-test-design.md) | 5 | Genuine-Chrome vs CloakBrowser differential harness (behavior + structure, not just values). |
| [05-stability-and-separation.md](05-stability-and-separation.md) | 6 | Same-profile stability + cross-profile separation suites; field stability classes. |
| [06-coherence-engine-design.md](06-coherence-engine-design.md) | 9 | Windows-only canonical device model: schema, generation, validation, migration, degradation. |
| [07-external-checker-policy.md](07-external-checker-policy.md) | 7, 8 | External-checker adapter policy + first-party local probe design. |
| [08-release-gates.md](08-release-gates.md) | 10 | Hard release blockers vs non-blocking telemetry. |

Implementation plan (separate, superpowers format):
[docs/superpowers/plans/2026-07-24-fingerprint-assurance.md](../../superpowers/plans/2026-07-24-fingerprint-assurance.md)

## Headline conclusion

The **identity core is genuinely good** and better than the reference/official manager on the
dimensions that matter most: a 64-bit CSPRNG seed with a DB uniqueness constraint, a stable seed
across edits, explicit-only regeneration, fresh identities on duplicate/import, a config-hash that
bumps only on identity changes — all covered by existing tests. The UI is refreshingly honest
(it *anti-promises* OS/screen spoofing rather than faking it).

The problems are at the **edges and the wiring**, not the core:

1. A cluster of advanced settings (permissions, geolocation, hardware concurrency, GPU vendor,
   humanize, WebRTC "disabled", color scheme, restore-tabs, download dir, extra args) is
   **stored, shown, and in two cases hashed — but never applied at launch**. Some are false
   security/privacy promises; two produce *phantom identity changes* (the hash moves, the browser
   does not).
2. Proxy-aligned geo **silently degrades to the host timezone/locale** when GeoIP enrichment fails.
3. WebRTC masking over a TCP SOCKS5 proxy is **structurally impossible at the wrapper layer** and
   its real effectiveness is unknown (binary-internal).
4. Custom UA and custom window size can create **incoherent, detectable contradictions**.

See [02-findings.md](02-findings.md) for the full, evidence-cited list and
[08-release-gates.md](08-release-gates.md) for what should block a release.
