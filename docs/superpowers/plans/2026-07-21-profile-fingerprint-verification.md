# Profile Fingerprint Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove whether CloakBrowser profiles are stable across relaunches and measurably different across unique seeds without collecting browsing secrets.

**Architecture:** The runtime subsystem opens a bundled local diagnostic document in an owned profile context, evaluates an allowlisted collector, canonicalizes the result, and stores only sanitized surface hashes and metadata. A comparison service reports per-surface stability/difference and explicitly marks unsupported or invariant surfaces.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2, CloakBrowser persistent contexts, SHA-256, pytest, bundled local HTML/JavaScript.

## Global Constraints

- No external fingerprinting website is required for the canonical test.
- Never capture cookies, storage, history, page content, credentials, proxy URLs, or authorization values.
- One profile is launched at a time through the owned runtime service.
- A stored seed difference alone is never reported as browser fingerprint uniqueness.
- Browser binary/version and fingerprint revision accompany every snapshot.

### Task 1: Allowlisted snapshot collector

**Files:**
- Create: `manager_backend/features/fingerprint_diagnostics/collector.js`
- Create: `manager_backend/features/fingerprint_diagnostics/schemas.py`
- Create: `manager_backend/features/fingerprint_diagnostics/collector.py`
- Test: `tests/manager/test_fingerprint_collector.py`

- [ ] Write a failing test asserting the collector schema accepts only user agent, platform, languages, timezone, hardware concurrency, screen/window geometry, WebGL vendor/renderer, Canvas hash, audio hash, and WebRTC classification.
- [ ] Run `python -m pytest -q tests/manager/test_fingerprint_collector.py` and verify the missing-module failure.
- [ ] Implement the bundled collector and strict Pydantic schema; hash raw Canvas/audio output in-page and discard raw bytes.
- [ ] Run the test and verify all collector contract cases pass.
- [ ] Commit with `git commit -m "feat(manager): add safe fingerprint snapshot collector"`.

### Task 2: Snapshot persistence and comparison

**Files:**
- Create: `manager_backend/features/fingerprint_diagnostics/models.py`
- Create: `manager_backend/migrations/versions/0003_fingerprint_snapshots.py`
- Create: `manager_backend/features/fingerprint_diagnostics/service.py`
- Test: `tests/manager/test_fingerprint_comparison.py`

- [ ] Write failing tests for stable repeats, cross-profile differences, invariant surfaces, unsupported values, and binary-version mismatches.
- [ ] Run the test and verify missing persistence/comparison interfaces.
- [ ] Store sanitized snapshots and implement per-surface `stable`, `different`, `invariant`, `unsupported`, and `not_comparable` results.
- [ ] Run migration checks and comparison tests.
- [ ] Commit with `git commit -m "feat(manager): compare fingerprint stability and differences"`.

### Task 3: Runtime diagnostic API

**Files:**
- Create: `manager_backend/features/fingerprint_diagnostics/routes.py`
- Modify: `manager_backend/api.py`
- Test: `tests/manager/test_fingerprint_diagnostic_api.py`

- [ ] Write failing authenticated API tests for starting a snapshot, retrieving a result, and comparing profiles.
- [ ] Run the test and verify missing routes.
- [ ] Add `/api/v1/profiles/{id}/fingerprint-snapshots` and `/api/v1/fingerprint-comparisons` using the owned runtime adapter and sanitized error envelope.
- [ ] Run manager contract tests and export the updated OpenAPI fixture.
- [ ] Commit with `git commit -m "feat(manager): expose fingerprint verification API"`.

### Task 4: Real-browser verification gate

**Files:**
- Create: `tests/manager/test_fingerprint_runtime_slow.py`
- Modify: `docs/PROFILE_FIELD_CAPABILITY_MATRIX.md`

- [ ] Add `slow` tests launching one profile twice and two profiles with different seeds.
- [ ] Verify same-profile seed/configuration stability and collect evidence for each browser-exposed surface.
- [ ] Verify cross-profile results without assuming every surface must differ.
- [ ] Document observed invariant or unsupported surfaces and whether a future Chromium patch is required.
- [ ] Commit with `git commit -m "test(manager): verify profile fingerprint behavior"`.
