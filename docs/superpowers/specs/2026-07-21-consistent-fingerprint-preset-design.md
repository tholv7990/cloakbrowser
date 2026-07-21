# Consistent Fingerprint Preset and Incognito Diagnosis Design

## Objective

Add a backward-compatible fingerprint consistency preset that avoids noise-based masking detection, then identify and fix Pixelscan's persistent-profile “Incognito Window” classification if the responsible signal is controlled by this repository.

## Public API

Add `fingerprint_preset` / `fingerprintPreset` to all launch modes:

- Python: `fingerprint_preset="consistent"`
- TypeScript: `fingerprintPreset: "consistent"`
- .NET: `FingerprintPreset = FingerprintPreset.Consistent`

Supported values:

- `default`: preserve current behavior and implicit binary noise.
- `consistent`: add `--fingerprint-noise=false`; for persistent contexts also add `--fingerprint-storage-quota=10240` unless explicitly overridden. A controlled stock Chrome comparison measured the same 10 GiB quota.

Unknown preset values raise a clear validation error before browser launch.

## Argument precedence

Final priority remains:

1. Platform stealth defaults.
2. Preset arguments.
3. Caller-provided `args`.
4. Dedicated timezone and locale parameters.

Arguments deduplicate by flag key, so callers can override either preset value explicitly, including `--fingerprint-noise=true` and another storage quota.

The preset does not generate or persist a seed. Callers managing returning identities must continue supplying a fixed `--fingerprint=<seed>` and a dedicated user-data directory.

## Cross-language parity

Implement equivalent behavior in:

- `cloakbrowser/browser.py`
- `js/src/args.ts`, `js/src/types.ts`, and launch callers
- `.NET LaunchOptions`, `Config`, and `CloakLauncher`

Add matching unit tests for validation, preset expansion, explicit overrides, and persistent-only quota behavior.

## Incognito root-cause matrix

Use the existing working SOCKS5 proxy without storing credentials in source or artifacts. Run headed, persistent profiles against Pixelscan with a fixed viewport and isolated profile directory for each case:

1. Installed stock Chrome persistent profile.
2. CloakBrowser persistent profile with `--fingerprint=off` when supported.
3. CloakBrowser default fingerprint.
4. CloakBrowser consistent preset.
5. Controlled changes to storage quota, storage persistence, cookies, filesystem API availability, service workers, IndexedDB, cache API, and profile preferences.

Capture the browser-visible signals and scan verdict for every case. Compare stock Chrome with CloakBrowser to identify the smallest differing signal correlated with the incognito label.

## Incognito implementation rule

- If the cause is wrapper-controlled, add a failing regression test, implement the smallest cross-language correction, and rerun Pixelscan.
- If the cause is specific to the free Chromium 146 binary, do not misrepresent a wrapper workaround as a fix. Record the evidence, test a compatible newer binary if locally entitled, and document the minimum binary requirement.
- If Pixelscan applies a proprietary heuristic that cannot be isolated reliably, report it as unresolved with the completed elimination matrix.

## Regression scanner

Create `benchmarks/fingerprint_scanners.py` with environment-only proxy input. It will:

- Use a unique persistent profile directory per case.
- Start the Pixelscan scan explicitly.
- Extract consistency, masking, automation, proxy, IP/WebRTC, timezone, and incognito verdicts.
- Save timestamped JSON and screenshots under `benchmarks/results/fingerprint-scanners/`.
- Redact proxy credentials from all output.
- Return nonzero when required consistent-preset checks fail.

Iphey is optional because its current scan remains stuck on temporary values; the script records that state without treating it as a CloakBrowser failure.

## Success criteria

- `consistent` produces “fingerprint consistent,” “no masking detected,” and “no automated behavior detected” in two consecutive Pixelscan runs using the same profile.
- IP and WebRTC equal the proxy exit IP, and timezone matches the IP location.
- Explicit caller arguments override preset arguments in all three clients.
- Existing default behavior and signatures remain compatible.
- The incognito label is either removed by a reproduced fix or documented with evidence showing why this wrapper cannot remove it.
- No proxy credentials appear in source, JSON, screenshots metadata, or documentation.

## Workspace limitation

This folder is not a Git repository, so the specification and implementation cannot be committed or isolated in a worktree.
