# Python Reusable Playwright Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backward-compatible sync and async session APIs that reuse one Playwright driver across multiple CloakBrowser launches.

**Architecture:** Extract already-started-driver launch helpers from `browser.py`; module-level launch functions keep owning a fresh driver, while session classes own a shared driver and all browsers they create. Tests use lightweight fakes to prove ownership and parity without timing thresholds.

**Tech Stack:** Python 3.9+, Playwright sync/async APIs, pytest, pytest-asyncio.

## Global Constraints

- Preserve all existing public launch signatures and behavior.
- No global Playwright cache or cross-event-loop state.
- Session exit closes leaked browsers before stopping Playwright exactly once.
- Support the full existing bare-browser launch option surface.
- Persistent and managed contexts remain outside this optimization.
- Do not change TypeScript, .NET, or the Chromium binary.

---

### Task 1: Extract driver-reusing launch helpers

**Files:**
- Modify: `cloakbrowser/browser.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Produce: `_launch_with_playwright(pw, **launch_options) -> Browser`
- Produce: `_launch_with_playwright_async(pw, **launch_options) -> Awaitable[Browser]`

- [ ] Write failing fake-driver tests asserting the helpers launch with the resolved executable, stealth arguments, ignored defaults, environment, and proxy values without starting or stopping Playwright.
- [ ] Run `python -m pytest tests/test_session.py -q` and confirm missing-helper failures.
- [ ] Extract the common preparation and post-launch viewport/humanization behavior from existing launch functions into the two helpers.
- [ ] Make module-level `launch()` and `launch_async()` start a driver, call the helper, and retain their close-to-stop ownership wrapper.
- [ ] Run `python -m pytest tests/test_session.py tests/test_launch.py tests/test_stealth_unit.py -q` and confirm relevant tests pass.

### Task 2: Implement public reusable sessions

**Files:**
- Create: `cloakbrowser/session.py`
- Modify: `cloakbrowser/__init__.py`
- Modify: `tests/test_session.py`

**Interfaces:**
- Produce: `CloakBrowserSession` with `__enter__`, `launch`, `close`, and `__exit__`.
- Produce: `AsyncCloakBrowserSession` with `__aenter__`, async `launch`, async `close`, and `__aexit__`.

- [ ] Add failing lifecycle tests for one driver start, multiple launches, browser-close independence, leaked-browser cleanup, one driver stop, double entry, launch outside active lifetime, and idempotent close.
- [ ] Run the session tests and confirm failures are caused by missing classes.
- [ ] Implement sync and async session ownership with explicit active/closed state and tracked browsers.
- [ ] Export both classes lazily from `cloakbrowser.__init__` and include them in `__all__`.
- [ ] Run session, launch, and import tests; confirm they pass.

### Task 3: Correct and extend benchmark

**Files:**
- Modify: `benchmarks/compare_chrome.py`
- Modify: `tests/test_benchmark_compare.py`
- Create at runtime: `benchmarks/results/cloakbrowser-session-vs-chrome-2026-07-21.json`

**Interfaces:**
- Main comparison: one shared Playwright driver for both executables.
- Metadata: separately measured Playwright driver initialization.
- Additional result: repeated legacy module-level launch timing.

- [ ] Add failing tests for separate driver-start summary and benchmark metadata.
- [ ] Refactor the runner to launch CloakBrowser through the shared-driver helper/session, compare stock Chrome through the same driver, and keep legacy measurements separate.
- [ ] Run benchmark unit tests and confirm they pass.
- [ ] Execute five alternating iterations and five-page concurrency; require zero errors.

### Task 4: Document and verify

**Files:**
- Modify: `README.md`
- Modify: `docs/CODEBASE_FUNCTIONALITY.md`

- [ ] Add sync/async session examples and explain when reuse matters.
- [ ] Replace the invalid benchmark interpretation with corrected raw results and clearly separate legacy driver startup.
- [ ] Run focused Python tests, benchmark tests, runtime session smoke tests, JSON schema validation, and documentation-value validation.
- [ ] Record any pre-existing unrelated suite failures without hiding them.

## Commit note

This workspace is not a Git repository, so no commit or worktree operations are available.

