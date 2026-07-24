# 07 — External Checker Policy & First-Party Probe (Audit Tasks 7 & 8)

## Current state

- Built-in diagnostics run only against `pixelscan / iphey / cloudflare / google_search` plus a
  `direct_google_control` (`manager_backend/models.py:283`, `features/diagnostics/`). No
  BrowserScan/BrowserLeaks/CreepJS/AmIUnique/Whoer.
- The UI does not run checks itself; it POSTs a run and renders a generic
  `findings: Record<string, bool|string>` map (frontend audit §G). There is **no first-party
  fingerprint probe** — orphaned `diag.kind.fingerprintCheck` i18n implies one was planned but never
  wired (F-020).
- The existing design already sets the right guardrails: local fixture pages + injected adapters in
  tests, live behind `CLOAK_LIVE_DIAGNOSTICS=1`, "observations not guarantees",
  CAPTCHA sets `warning` and is never solved
  (`specs/2026-07-22-manager-fingerprint-diagnostics-design.md`).

## Part A — External checker adapter policy (Audit Task 7)

External checkers are **best-effort telemetry**, never a hard CI gate. A checker changing its wording
or DOM must not fail a build.

### Record schema (per external run)

```jsonc
{
  "provider": "pixelscan",
  "provider_category": "fingerprint|ip|captcha",
  "timestamp": "2026-07-24T09:00:00Z",
  "result_status": "observed|inconclusive|error|timeout",  // never a bare pass/fail
  "sanitized_findings": { "webrtc_leak": false, "timezone_match": true },  // booleans/enums only
  "screenshot_path": "reports/<run>/shot.png",             // local path, redacted of chrome
  "binary": { "version": "146.0.7680.177", "sha256": "…" },
  "fingerprint": { "revision": 3, "config_hash": "…" },     // never the seed
  "mode": "manual|automated",
  "proxy": { "type": "socks5", "asn": "AS####", "country": "US" },  // anonymized
  "duration_ms": 4200,
  "error_code": null
}
```

### Hard constraints (enforced, not aspirational)

- **No brittle scrape is a required CI dependency.** External runs are opt-in
  (`CLOAK_LIVE_DIAGNOSTICS=1`), matching the current design.
- **Third-party UI/wording changes must not fail core tests** — adapters map to a stable internal
  enum; an unrecognized layout yields `inconclusive`, not a failure.
- **CAPTCHA frequency is telemetry, not a fingerprint verdict** — a Turnstile/reCAPTCHA appearing
  sets `warning`/records occurrence; it never counts as a fingerprint failure and is **never
  solved** (already the stance, `en.ts` `diag.noCaptcha`).
- **Never store secrets:** no cookies, no proxy passwords, no account identifiers, no page content
  that could contain secrets. Only booleans/enums + a screenshot. Redact local paths and the machine
  username from every artifact (paths, screenshots) — the capability matrix already forbids
  cookies/storage/history/credentials in snapshots (`PROFILE_FIELD_CAPABILITY_MATRIX.md:57`).
- **Respect ToS + rate limits:** per-provider minimum interval; back off on 429; document that these
  hit third-party sites.

## Part B — First-party local probe (Audit Task 8)

The trustworthy core: a probe Plasma controls end-to-end, no third party, no network.

### What it collects (normalized JSON, schema-versioned)

UA + Client Hints · Navigator · Canvas + OffscreenCanvas · WebGL/WebGL2 · WebGPU · Audio ·
Fonts/text metrics · Screen/viewport/DPR · Locale/timezone · Geolocation availability · WebRTC
(ICE candidates vs local STUN) · Media devices · Speech voices · Permissions/plugins · Automation
indicators · Native-API integrity (descriptors, prototype chain, `toString` — the structural checks
from [04](04-differential-test-design.md)).

### Hard requirements (from the brief)

- Collects **no** website credentials, **no** cookies, **no** browser history.
- **Does not phone home** — runs against a **local** page, writes a local JSON report.
- **Deterministic fixture testing** — a checked-in fixture page + golden output; CI runs offline.
- **Separates raw observation from verdict** — the JSON has a `raw` block and a separate `verdict`
  block; a verdict is computed from raw, never conflated (mirrors the existing per-surface state
  model `stable|different|invariant|unsupported|not_comparable`).
- **Schema versioning** — `probe_schema_version`; goldens regenerate on a Chromium bump.
- **Redaction** — strip local paths and the machine username from all output.

### Verdict vocabulary (per surface)

`stable | different | invariant | unsupported | not_comparable` for stability/separation, plus
`coherent | contradictory` for cross-layer checks (e.g. UA-vs-CH, window-vs-screen, tz-vs-IP). A
stored-seed difference alone is **never** reported as fingerprint uniqueness
(`PROFILE_FIELD_CAPABILITY_MATRIX.md:58`).

### Where it should live — recommendation

Three options were considered:

1. **Inside the existing diagnostics feature** (`manager_backend/features/diagnostics/`) as a new
   `kind` — reuses the persisted-run model, the exact launch snapshot
   (`test_diagnostic_runner.py:282`), and the UI. **Recommended.**
2. A separate local static test site — more isolated but duplicates run/report plumbing.
3. A separate trusted local test service — needed only for **Tier 2** (TLS/HTTP2/WebRTC-UDP origin,
   [04](04-differential-test-design.md)), which genuinely cannot run in-page.

**Recommendation:** build the in-page probe as option 1 (it reuses the exact launch builder, so the
probe measures what real profiles present, and the diagnostics UI/artifacts already exist), and add
the controlled server (option 3) **only** for the Tier-2 surfaces JS cannot see. Wire the orphaned
`diag.kind.fingerprintCheck` string to this new kind (closes part of F-020).

This probe is the enforcement backbone for the release gates in [08](08-release-gates.md): it is what
lets diagnostics report a surface as "applied" only after read-back (F-004), and it is what actually
measures the WebRTC host-candidate question (F-003).
