# Task 3: Controlled cookie browser operations report

## Scope

Implemented authenticated cookie import/export endpoints for stopped profiles,
backed by an injected `CookieContextAdapter` and the accepted bounded cookie
parser.

Changed files:

- `manager_backend/features/portability/browser_cookies.py`
- `manager_backend/features/portability/routes.py`
- `manager_backend/features/portability/schemas.py`
- `manager_backend/features/runtime/launcher.py`
- `manager_backend/features/runtime/manager.py`
- `manager_backend/main.py`
- `tests/manager/test_cookie_api.py`

The runtime launcher and manager were changed only to extract and share the
existing normal profile snapshot/context options. This prevents the cookie
adapter from drifting from normal Manager launches while setting `headless=True`
for the short-lived cookie context.

## TDD evidence

### RED: cookie endpoint absent

Command:

```powershell
python -m pytest tests/manager/test_cookie_api.py::test_json_cookie_import_uses_adapter_and_reports_safe_counts -q
```

Result (exit code 1):

```text
E       assert 404 == 200
1 failed, 1 warning in 0.52s
```

### RED: expanded API and adapter contract

Command:

```powershell
python -m pytest tests/manager/test_cookie_api.py -q
```

Result before the multipart/export/adapter implementation (exit code 1):

```text
10 failed, 5 passed, 1 warning in 3.33s
```

The failures were the intended missing behaviors: multipart parsing, export,
export stopped-state/authentication routing, safe adapter failure mapping, and
the absent real browser cookie adapter.

### RED: adapter-level stopped-state defense

Command:

```powershell
python -m pytest tests/manager/test_cookie_api.py::test_cookie_context_adapter_rejects_a_running_profile_before_launch -q
```

Result (exit code 1):

```text
E       AssertionError: assert 'cookie_operation_failed' == 'profile_not_stopped'
1 failed, 1 warning in 0.21s
```

### GREEN: focused cookie and runtime compatibility tests

Command:

```powershell
python -m pytest tests/manager/test_cookie_api.py tests/manager/test_cookie_formats.py tests/manager/test_runtime_manager.py -q
```

Result (exit code 0):

```text
78 passed, 1 warning in 4.19s
```

## Final verification

Command:

```powershell
python -m pytest tests/manager -q
```

Result (exit code 0):

```text
313 passed, 2 skipped, 1 warning in 38.11s
```

The warning is the existing FastAPI/TestClient deprecation warning for the
installed `httpx` version. The two skips are existing platform/environment
skips.

Additional checks:

- `python -m compileall -q manager_backend` exited 0.
- Scoped `git diff --check` exited 0.
- A source scan found no SQLite, decryption, or logging access in the new cookie
  adapter/routes/tests.

## Security and behavior review

- Import supports strict JSON `{format, content}` and multipart `format` +
  `file` contracts for `json`, `playwright`, and `netscape`.
- The complete HTTP request is streamed into a bounded 10 MiB buffer before
  JSON or multipart parsing; declared and observed oversize requests return
  HTTP 413. The accepted parser independently enforces 10 MiB and 10,000-cookie
  limits and performs field validation.
- Both routes require the existing authenticated API dependency. Import also
  requires exact allowed Origin and CSRF through the existing mutation policy.
- Both the route and adapter require `runtime_state == stopped`. The adapter
  also takes the same profile file lock as normal runtime launches, closing the
  state-check/launch race.
- The real adapter launches the profile's normal persistent user-data directory
  with the shared fingerprint, pinned browser version, custom user agent,
  locale, timezone, and resolved proxy configuration, but forces headless mode.
- Cookie access is exclusively through Playwright `add_cookies()` and
  `cookies()`. The short-lived context closes in `finally`, the profile lock is
  released even after operation or cleanup failure, and failures map to fixed,
  value-free errors.
- Export values appear only in the authenticated attachment response. Downloads
  have ASCII-safe filenames, `Cache-Control: no-store`, and
  `X-Content-Type-Options: nosniff`. No cookie values are logged or persisted in
  Manager tables.

## Concerns

None. The 10 MiB ceiling intentionally applies to the complete multipart HTTP
request, including its small framing overhead, matching the design's request
limit and ensuring multipart parsing never sees an oversized request.

## Review fix: event-loop-safe synchronous browser import

The original async import route streamed the request safely but then called the
synchronous cookie parser and `CookieContextAdapter` directly on the asyncio
event-loop thread. CloakBrowser's synchronous Playwright API rejects that usage.
The adapter also owned a proxy resolver that opened a database session, so
wrapping the old adapter call in `to_thread()` would have moved both an ORM
profile and database work across threads.

The route now resolves the proxy and creates a frozen `CookieProfileConfig` on
the request thread. The owned worker receives only the adapter, immutable config,
format, and bytes/string content; it performs JSON envelope decoding, accepted
cookie parsing, context launch/import, and cleanup together. The request awaits
the worker through `asyncio.shield()`, while a strong task registry retains a
cancelled request's worker until its adapter `finally` cleanup completes.

Content-Type dispatch now compares the exact case-folded base media type while
allowing parameters. The buffered multipart request normalizes the base media
type before Starlette parsing so valid mixed-case multipart types remain
accepted, while prefix lookalikes are rejected before parsing.

### RED

Command:

```powershell
python -m pytest tests/manager/test_cookie_api.py::test_import_route_offloads_real_adapter_and_playwright_probe tests/manager/test_cookie_api.py::test_cookie_json_content_type_requires_an_exact_base_media_type tests/manager/test_cookie_api.py::test_cookie_multipart_content_type_requires_an_exact_base_media_type -q
```

Result before the fix (exit code 1):

```text
3 failed, 2 warnings in 1.78s
```

The real `sync_playwright()` guard returned HTTP 500 on the route loop,
`application/jsonp` returned HTTP 200, and the multipart lookalike reached the
form parser.

The cancellation ownership test also failed before implementation because the
owned worker helper did not exist:

```text
1 failed, 1 warning in 0.37s
```

A positive mixed-case multipart regression then exposed Starlette's
case-sensitive base media-type dispatch:

```text
1 failed, 21 passed, 1 warning in 4.55s
```

### GREEN

Focused command:

```powershell
python -m pytest tests/manager/test_cookie_api.py tests/manager/test_cookie_formats.py tests/manager/test_runtime_manager.py -q
```

Result (exit code 0):

```text
84 passed, 1 warning in 5.76s
```

Full Manager command:

```powershell
python -m pytest tests/manager -q
```

Result (exit code 0):

```text
319 passed, 2 skipped, 1 warning in 37.18s
```

The warning and skips are the same third-party/platform items noted above.
