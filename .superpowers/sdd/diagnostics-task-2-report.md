# Fingerprint Diagnostics Task 2 Report

## Status

Complete. The injected diagnostic runner and artifact boundary are implemented, verified, and confined to the Manager backend. No frontend work, public navigation, target-specific extraction, or push was performed.

## Delivered

- Added `DiagnosticRunner.run(request, cancel_event, progress) -> DiagnosticResult` with injected browser, target, proxy-preflight, and profile-lock boundaries.
- Enforced the exact server-owned HTTPS URL for each diagnostic kind before any profile lookup, preflight, or browser launch.
- Required profile diagnostics to acquire the normal runtime lock and observe no active runtime before launch.
- Reused `profile_launch_snapshot` and `enabled_profile_extension_paths` for profile runs. The canonical snapshot now carries fingerprint revision/hash plus complete location, window, and behavior dictionaries in addition to the existing fingerprint, browser version, user-agent, proxy, and extension inputs.
- Ran proxy preflight before every profile browser launch; any preflight exception maps to `proxy_preflight_failed` without launching or persisting raw details.
- Created direct controls with a temporary manager-owned profile below the exact diagnostic run root, no proxy, no extensions, and installed-version resolution so the global CloakBrowser tier/version remains authoritative.
- Added bounded Manager settings for diagnostic concurrency, total adapter deadline, report bytes, and screenshot bytes. A supervisor hard-enforces the total deadline/cancellation even when a synchronous adapter ignores its inputs, while the lifecycle adapter still receives the remaining timeout and cancellation event.
- Added stable mappings for timeout, browser crash, network, proxy-preflight, stopped-state, and unexpected failures. Adapter-provided status/error pairs are normalized before persistence.
- Added atomic `report.json` and optional `screenshot.png` writes below `<data_root>/diagnostics/<uuid>`, with exact UUID roots, resolved containment, junction rejection, bounded payloads, and temporary-file cleanup.
- Reports contain only bounded browser identity, fingerprint revision/hash, credential-free proxy observation metadata, allowlisted target data, bounded title/findings, timings, and fixed limitations. Fingerprint seeds, proxy URLs, arbitrary exceptions, DOM, cookies, storage, and response/network bodies are not persisted.
- Guaranteed browser close, temporary-profile removal, runtime-lock release, and semaphore release through `finally` cleanup. Cancellation returns the typed `cancelled` runner result for Task 4 lifecycle handling.

## TDD Evidence

Initial RED:

```text
python -m pytest tests/manager/test_diagnostic_runner.py -q
ERROR tests/manager/test_diagnostic_runner.py
ModuleNotFoundError: No module named 'manager_backend.features.diagnostics.artifacts'
```

Safety-review RED:

```text
python -m pytest tests/manager/test_diagnostic_runner.py -q -k normalizes_adapter_error_codes
4 failed, 20 deselected
```

Direct-report RED:

```text
python -m pytest tests/manager/test_diagnostic_runner.py::test_direct_control_uses_and_removes_a_manager_owned_no_proxy_profile -q
1 failed
```

Final focused GREEN:

```text
python -m pytest tests/manager/test_diagnostic_runner.py -q
24 passed, 1 warning in 1.25s
```

The focused suite covers stopped state, exact profile snapshot reuse, extensions/config preservation, direct temporary profile semantics, proxy preflight ordering/failure, URL allowlisting, timeout/crash/network/generic mapping, adapter-code sanitization, report secrecy, exact-root artifact writes, traversal rejection, a real Windows junction regression, cancellation cleanup, and concurrency bounds.

## Verification

Affected compatibility gate:

```text
python -m pytest tests/manager/test_runtime_manager.py tests/manager/test_diagnostics_api.py tests/manager/test_config.py -q
59 passed, 1 warning in 8.83s
```

Full Manager gate:

```text
python -m pytest tests/manager -q
430 passed, 3 skipped, 1 warning in 57.20s

python -m compileall -q manager_backend
exit 0
```

The sole warning is the pre-existing Starlette `TestClient`/`httpx` deprecation warning.

## Scope and Follow-up

- The browser and target adapters are deliberately injected. Task 2 performs no public-site navigation by itself.
- Target-specific selectors, normalization, CAPTCHA detection, and visible-label extraction remain Task 3.
- Scheduling, persistence transitions, cancellation-to-database handling, events, and app lifecycle wiring remain Task 4.
- The worktree is preserved on its existing feature branch; no merge, PR, push, frontend change, or generated OpenAPI change was made.

## Independent Review Correction Pass

All Important independent-review findings were reproduced and corrected in a second TDD pass.

- Browser launch, target execution, and graceful close now remain on one lifecycle owner thread for compatibility with synchronous browser APIs.
- Preflight and lifecycle calls run behind a hard supervisor deadline. A 200 ms non-cooperative adapter cannot pass or block a 50 ms diagnostic deadline, and an adapter that ignores cancellation cannot turn the result into a pass.
- Deadline/cancellation sets an internal abort event and invokes only the session's thread-safe forced-termination boundary from the supervisor. Late lifecycle completion is reaped by a manager-owned daemon cleanup worker.
- A profile lock and concurrency slot remain leased until a late browser launch has closed or terminated and reported cleanup. If cleanup cannot be verified, neither is released.
- Graceful-close errors invoke `terminate()` and verify `is_closed()`. Close, terminate, lock-release, or temporary-profile-removal failures map to stable `cleanup_failed`; they never return `passed` or unsafe `cancelled` outcomes.
- Profile diagnostics force `startup_urls=[]`; the canonical fingerprint, proxy, GeoIP/location, window, behavior, and enabled-extension configuration is otherwise preserved exactly.
- Final redirects are retained only for the diagnostic kind's explicit HTTPS host policy. Userinfo, nonstandard ports, queries, and fragments are stripped. Google consent and `/sorry` paths remain observable without persisting their query data.
- Added oversized report/screenshot rejection tests and atomic-write interruption coverage proving temporary files are removed.

Review RED evidence:

```text
python -m pytest tests/manager/test_diagnostic_runner.py -q -k "suppresses_normal_startup_urls or total_deadline_rejects or non_cooperative_target"
5 failed, 24 deselected

python -m pytest tests/manager/test_diagnostic_runner.py -q -k "close_failure or unverified_browser_cleanup or removal_failure or sanitized_allowed_https_redirects"
9 failed

python -m pytest tests/manager/test_diagnostic_runner.py::test_sync_browser_lifecycle_stays_on_one_owner_thread -q
1 failed
```

Final review verification:

```text
python -m pytest tests/manager/test_diagnostic_runner.py -q
43 passed, 1 warning in 3.44s

# Five repetitions of deadline/cancellation/cleanup races
5 x 7 passed (35 stress cases)

# Twenty repetitions of cooperative and ignored cancellation
20 x 2 passed (40 stress cases)

python -m pytest tests/manager/test_runtime_manager.py tests/manager/test_diagnostics_api.py tests/manager/test_config.py -q
59 passed, 1 warning in 8.65s

python -m pytest tests/manager -q
449 passed, 3 skipped, 1 warning in 71.53s

python -m compileall -q manager_backend
exit 0
```

Python cannot safely kill a truly never-returning thread. The fail-safe contract therefore terminates and verifies any published browser session, retains the lock/semaphore lease, and keeps the owner/reaper as daemon threads until the adapter returns. This prevents an unverified browser from overlapping another launch. Finite non-cooperative adapters are hard-bounded and fully reaped; an adapter that both never returns and hides an external process before publishing its session violates the injected adapter contract and is intentionally never treated as cleaned up.
