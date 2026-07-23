# Fast Proxy Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce proxied profile startup latency while preserving the rule that an unavailable proxy blocks launch.

**Architecture:** Keep the detailed three-sample proxy test for manual diagnostics, but give runtime launch a bounded fast path. Runtime preflight honors the profile toggle, reuses a recent successful result, shares its exit IP with the browser fingerprint arguments, and runs before the scarce Chromium-launch semaphore.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, pytest, httpx.

## Global Constraints

- Never expose proxy credentials in logs, exceptions, database fields, or API responses.
- A required preflight must reject an unavailable proxy before Chromium launches.
- The complete runtime preflight, including optional geolocation, has a five-second absolute deadline.
- A successful cached result is reusable for 60 seconds only when it is newer than the proxy row's last update.
- Manual “Check Proxy” behavior remains the detailed diagnostic path.

---

### Task 1: Honor the profile launch setting

**Files:**
- Modify: `manager_backend/features/runtime/launcher.py`
- Modify: `manager_backend/features/proxies/service.py`
- Test: `tests/manager/test_runtime_manager.py`
- Test: `tests/manager/test_proxy_quick_test.py`

**Interfaces:**
- Produces: launch snapshot key `test_proxy_before_launch: bool`
- Consumes: `Profile.test_proxy_before_launch`

- [ ] Add failing tests proving the snapshot carries the toggle and disabled preflight resolves the proxy URL without calling the tester.
- [ ] Run the focused tests and verify the expected failures.
- [ ] Add the snapshot key and short-circuit connectivity testing when disabled.
- [ ] Run the focused tests and verify they pass.

### Task 2: Reuse recent successful preflight results

**Files:**
- Modify: `manager_backend/features/proxies/service.py`
- Test: `tests/manager/test_proxy_quick_test.py`

**Interfaces:**
- Produces: `_cached_quick_test(proxy, now, max_age)` returning `QuickTestResult | None`
- Consumes: persisted safe proxy result fields and timestamps.

- [ ] Add failing tests for fresh reuse, stale rejection, and invalidation after proxy modification.
- [ ] Run the focused tests and verify the expected failures.
- [ ] Implement the 60-second cache eligibility check and safe result reconstruction.
- [ ] Run the focused tests and verify they pass.

### Task 3: Bound the runtime fast test by one deadline

**Files:**
- Modify: `manager_backend/features/proxies/testing.py`
- Modify: `manager_backend/features/proxies/service.py`
- Test: `tests/manager/test_proxy_quick_test.py`

**Interfaces:**
- Produces: `ScannerQuickTester.run_fast(proxy_url, timeout_seconds=5) -> QuickTestResult`
- Consumes: injected resolver and geolocation lookup.

- [ ] Add failing tests proving slow geolocation cannot exceed the total deadline and launch preflight uses `run_fast`.
- [ ] Run the focused tests and verify the expected failures.
- [ ] Implement a single-sample fast resolver and deadline-bounded best-effort geolocation.
- [ ] Run the focused tests and verify they pass.

### Task 4: Eliminate duplicate engine exit-IP resolution

**Files:**
- Modify: `manager_backend/features/proxies/service.py`
- Modify: `manager_backend/features/runtime/launcher.py`
- Test: `tests/manager/test_runtime_manager.py`

**Interfaces:**
- Produces: snapshot key `proxy_exit_ip: str | None`
- Consumes: successful fresh or newly measured preflight result.

- [ ] Add failing tests proving the launch arguments contain the measured IP and never contain `auto`.
- [ ] Run the focused tests and verify the expected failures.
- [ ] Store the safe exit IP in the snapshot and construct `--fingerprint-webrtc-ip=<ip>`.
- [ ] Run the focused tests and verify they pass.

### Task 5: Remove network preflight from launch-slot contention

**Files:**
- Modify: `manager_backend/features/runtime/worker.py`
- Test: `tests/manager/test_runtime_manager.py`

**Interfaces:**
- Consumes: existing `proxy_preflight(snapshot)` and `launch_semaphore`.

- [ ] Add a failing concurrency test proving a blocked preflight does not consume the only Chromium launch slot.
- [ ] Run the test and verify it fails for semaphore contention.
- [ ] Move state transition and preflight immediately before the semaphore; keep only `launcher.launch` and ownership transition inside it.
- [ ] Run the focused test suite and verify it passes.

### Task 6: Verification

**Files:**
- Test: `tests/manager/`

- [ ] Run `pytest tests/manager/test_proxy_quick_test.py tests/manager/test_runtime_manager.py -q`.
- [ ] Run `pytest tests/manager -m "not slow" -q`.
- [ ] Review `git diff --check`, `git status --short`, and the final diff for secret leakage or unrelated changes.
