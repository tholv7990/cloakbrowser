# Task 4 report: passive browser site-state checks

## Scope

Created the required passive site-state module and its offline tests:

- `benchmarks/proxy_site_checks.py`
- `tests/test_proxy_site_checks.py`
- sanitized fixtures in `tests/fixtures/proxy_quality/`

No CLI orchestration or Git operations were performed.

## Implementation

- `parse_google_state()` applies the required priority: `/sorry/` or observed reCAPTCHA visibility, explicit access denial, observed `#search` visibility, consent, then unknown. Body text mentioning reCAPTCHA alone is not treated as a challenge.
- `parse_cloudflare_state()` applies the required priority: a nonempty observed response token without a visible challenge, visible challenge, explicit error, widget pending, then unknown.
- `run_browser_checks()` launches a persistent context with the supplied profile directory, proxy, GeoIP, humanization, consistent fingerprint preset, and `--fingerprint=63003`.
- Each protected site has one monotonic deadline that covers navigation, state observation, polling, and screenshot capture: 20 seconds for Cloudflare and 15 seconds for Google. Every Playwright timeout is calculated from the remaining deadline, so navigation cannot receive a separate full polling budget.
- The browser flow performs one navigation to the specified Cloudflare Turnstile demo and one fixed Google query. It only observes state, waits within the required limits, captures `cloudflare.png` and `google.png` when time remains, and never clicks or retries.
- A visible Cloudflare widget selector produces `pending` when there is no passed token, visible challenge, or explicit error, even when body text does not mention Turnstile.
- The result contains only per-site string verdicts and screenshot-success booleans. It omits the proxy, profile path, screenshot paths, page content, cookies, headers, storage, and any response token.
- Browser launch, navigation, screenshot, and close failures are handled without returning exception text. The persistent context is closed in `finally` whenever it was created.

## Offline fixtures and tests

Sanitized text fixtures cover Google results that mention reCAPTCHA, a Google sorry page, Google consent text, Cloudflare success text, and Cloudflare error text.

The test suite is fully offline. The browser-launch test monkeypatches `launch_persistent_context` and verifies the exact safe launch configuration, exactly one navigation per site, context closure, screenshot capture, and the returned redacted-safe shape. It never invokes a live browser or challenge.

## TDD evidence

1. RED: `python -m pytest tests/test_proxy_site_checks.py -q` failed during collection with `ModuleNotFoundError: No module named 'benchmarks.proxy_site_checks'` before production code existed.
2. GREEN: after the minimal module implementation, the same suite passed with `9 passed` and `python -m py_compile benchmarks/proxy_site_checks.py` exited successfully.
3. RED: the added explicit Cloudflare error test failed as expected: `assert 'unknown' == 'error'` for `Error: validation failed`.
4. GREEN: after the minimal parser adjustment, the required final commands passed: `10 passed in 0.17s`; `python -m py_compile benchmarks/proxy_site_checks.py` exited 0.
5. Reviewer RED: deterministic deadline and selector-only widget tests failed as expected. The simulated clock reached `48.0` seconds because navigation received a separate full polling window, and `_wait_for_cloudflare_state(..., deadline=...)` was unsupported.
6. Reviewer GREEN: after introducing shared absolute deadlines and selector-aware pending detection, `python -m pytest tests/test_proxy_site_checks.py -q` reported `12 passed in 0.16s`; `python -m py_compile benchmarks/proxy_site_checks.py` exited 0.

## Self-review and concerns

- Reviewed the requested priority order, safe output shape, browser launch arguments, timeout limits, one-navigation constraint, screenshot names, non-interaction rule, and context cleanup.
- The Cloudflare target is intentionally reported only as a third-party demo state, not as a general proxy reputation conclusion.
- Visibility selectors are conservative; unfamiliar page redesigns safely degrade to `pending` or `unknown` rather than attempting interaction or retrying. If the entire per-site deadline is consumed before capture, the corresponding `screenshot_captured` value is safely `False`.
