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
- Added bounded Manager settings for diagnostic concurrency, total adapter deadline, report bytes, and screenshot bytes. Remaining timeout and cancellation are passed into each injected browser/target adapter, while the runner uses an interruptible bounded semaphore.
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
