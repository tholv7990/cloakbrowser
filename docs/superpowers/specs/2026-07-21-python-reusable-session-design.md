# Python Reusable Playwright Session Design

## Objective

Remove repeated Playwright driver startup overhead from Python workloads that launch multiple CloakBrowser instances, while preserving the behavior and compatibility of all existing launch functions.

## Public API

Add two exported classes:

```python
from cloakbrowser import CloakBrowserSession, AsyncCloakBrowserSession
```

Synchronous use:

```python
with CloakBrowserSession() as session:
    browser = session.launch(headless=True)
    browser.close()
```

Asynchronous use:

```python
async with AsyncCloakBrowserSession() as session:
    browser = await session.launch(headless=True)
    await browser.close()
```

Each session exposes the same launch keyword arguments as the existing `launch()` or `launch_async()` API. A session may launch multiple browsers sequentially or concurrently while active.

## Ownership and lifecycle

- Entering a session starts exactly one Playwright driver.
- Each session-launched browser owns only its browser process; `browser.close()` does not stop the shared driver.
- Exiting the session closes any still-open browsers started by that session, then stops Playwright exactly once.
- Explicitly closed browsers are harmless during session cleanup.
- Calling `launch()` before entering or after exiting raises `RuntimeError` with a clear lifecycle message.
- Entering the same active session twice raises `RuntimeError`.
- Session exit is idempotent after a completed exit.
- If browser launch fails, the session remains usable for a later launch unless Playwright itself has stopped.
- Existing module-level `launch()` and `launch_async()` retain their current independent-driver ownership and cleanup behavior.

## Implementation structure

- Create `cloakbrowser/session.py` for both session classes and shared launch-preparation helpers.
- Reuse the existing binary, GeoIP, proxy, WebRTC, argument-building, license-environment, viewport, and humanization logic rather than duplicating behavior.
- Refactor `cloakbrowser/browser.py` only enough to expose internal helpers that launch through an already-started Playwright object.
- Export both session classes lazily from `cloakbrowser/__init__.py` to avoid importing Playwright until used.

## Behavioral parity

Session launches must support:

- Headless/headed mode.
- Proxy URLs and structured proxy settings.
- Extra and default stealth arguments.
- Timezone, locale, and GeoIP.
- Humanization presets and overrides.
- Extension paths.
- License keys and binary version pins.
- Arbitrary Playwright launch keyword arguments.
- License-error mapping identical to existing launch functions.
- Default viewport behavior identical to existing launch functions.

Persistent-context and managed-context session methods are outside this first optimization. The initial API optimizes repeated bare-browser launches, which is the measured bottleneck.

## Testing

Add unit tests proving:

- One Playwright start supports multiple launches.
- Closing browsers does not stop the session driver.
- Session exit closes leaked browsers and stops the driver once.
- Sync and async lifecycle behavior matches.
- Invalid lifecycle calls raise clear errors.
- Launch arguments, proxy, environment, humanization, and viewport behavior remain aligned with module-level launch.
- Existing launch tests still pass.

Add a performance regression check that compares repeated module-level launches with repeated session launches and asserts that the session avoids repeated driver starts. Do not use a strict wall-clock threshold in unit tests.

## Benchmark

Update `benchmarks/compare_chrome.py` so the main comparison uses one shared driver for both CloakBrowser and Chrome. Report Playwright driver initialization separately. Add an optional mode measuring the legacy module-level CloakBrowser API so users can see the benefit of the new session.

Rerun five alternating iterations plus five-page concurrency, store a new raw JSON artifact, and replace the invalid launch/concurrency interpretation in `docs/CODEBASE_FUNCTIONALITY.md`.

## Compatibility and scope

- No removal or signature change to existing public functions.
- No global Playwright cache.
- No changes to the patched Chromium binary.
- No changes to TypeScript or .NET in this iteration because their lifecycle implementations differ and the measured issue is specific to Python.
- The workspace is not a Git repository, so changes cannot be committed or isolated in a worktree.

