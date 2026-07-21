# Consistent Fingerprint Preset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a cross-language consistency preset, validate it through unit tests and repeated Pixelscan scans, and isolate the persistent-profile incognito signal.

**Architecture:** Each client expands a validated preset into ordinary Chromium arguments before its existing key-based argument merge. A standalone scanner consumes proxy credentials only from the environment and records redacted evidence. Incognito investigation compares isolated stock Chrome and CloakBrowser persistent profiles without changing production behavior until a causal signal is proven.

**Tech Stack:** Python/pytest/Playwright, TypeScript/Vitest, C#/.NET tests, JSON, Pixelscan.

## Global Constraints

- Preserve default launch behavior.
- Caller arguments override preset arguments.
- Apply storage quota only to persistent-context consistent presets.
- Keep all three client ports behaviorally aligned.
- Never store proxy credentials.
- Do not claim an incognito fix without a reproduced causal test.

### Task 1: Python preset

**Files:** `cloakbrowser/browser.py`, `tests/test_fingerprint_preset.py`

- [x] Write failing tests for validation, expansion, override precedence, and persistent-only quota.
- [x] Run the focused tests and confirm missing behavior.
- [x] Implement preset validation and argument expansion in every Python launch mode.
- [x] Run launch, context, persistent-context, and preset tests.

### Task 2: TypeScript and .NET parity

**Files:** `js/src/types.ts`, `js/src/args.ts`, JS tests, `.NET LaunchOptions.cs`, `Config.cs`, `CloakLauncher.cs`, .NET tests.

- [x] Add failing TypeScript and .NET tests matching Python expectations.
- [x] Implement equivalent preset types, validation, expansion, and precedence.
- [x] Run TypeScript typecheck/tests; .NET SDK was unavailable on this host.

### Task 3: Scanner regression tool

**Files:** `benchmarks/fingerprint_scanners.py`, `tests/test_fingerprint_scanners.py`

- [x] Add failing redaction and verdict-parser tests.
- [x] Implement environment-only proxy loading, scan execution, screenshots, JSON, and nonzero failure status.
- [x] Run unit tests and two consecutive consistent-preset scans.

### Task 4: Incognito diagnosis and documentation

**Files:** scanner JSON/screenshots, `README.md`, `docs/CODEBASE_FUNCTIONALITY.md`.

- [x] Compare stock Chrome and CloakBrowser persistent-profile storage/browser signals.
- [x] Add a regression test and correction after proving storage quota as the wrapper-controlled cause.
- [x] Document preset usage, verified Pixelscan results, incognito evidence, and limitations.
- [x] Run fresh compilation, focused tests, scanner artifact validation, and credential scans.

## Commit note

The workspace is not a Git repository, so commit and worktree steps are unavailable.
