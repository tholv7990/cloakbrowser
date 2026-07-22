# Portability Task 1 Report

## Status

Implemented versioned profile export/import for the Manager backend. The implementation is strict, secret/path/ID-free, bounded to 2 MiB at the streaming HTTP boundary, transactional, and registered under `/api/v1`.

## RED

- Initial focused run: `python -m pytest tests/manager/test_profile_portability.py -q`
  - Expected collection failure: `ModuleNotFoundError: No module named 'manager_backend.features.portability'`.
- Determinism/version hardening RED:
  - Permission-map order was not canonical.
  - Pydantic accepted `true` and `1.0` as version `1`.
- Rollback safety RED:
  - A pre-existing empty profile directory was removed after an `exist_ok=False` collision.
- Download-header RED:
  - `Cache-Control: no-store` and `X-Content-Type-Options: nosniff` were absent.
- Review-fix RED:
  - The route used `request.body()` before enforcing the byte limit.
  - Coercive values such as `"false"`, `0`, and string window dimensions were accepted.

Each RED failed for the intended missing or incorrect behavior before its production change.

## GREEN

- Focused: `python -m pytest tests/manager/test_profile_portability.py -q`
  - `19 passed, 1 warning in 2.04s`.
- Full Manager: `python -m pytest tests/manager -q`
  - `229 passed, 2 skipped, 1 warning in 31.90s`.
- Compile: `python -m compileall -q manager_backend/features/portability tests/manager/test_profile_portability.py`
  - Exit code 0.
- The warning is the pre-existing FastAPI TestClient `StarletteDeprecationWarning` about `httpx`/`httpx2`.

## Files

- Created `manager_backend/features/portability/schemas.py`
  - Strict v1 document, portable profile/catalog/proxy/extension metadata, result/warning models, and 2 MiB constant.
- Created `manager_backend/features/portability/profiles.py`
  - Deterministic secret-free export; normalized catalog resolution/creation; fresh UUID, seed, revision, and hash; collision naming; warnings; single-commit rollback-safe import and directory handling.
- Created `manager_backend/features/portability/routes.py`
  - Authenticated export/import routes, bounded streaming input, safe validation errors, sanitized download filename, `no-store`, and `nosniff` headers.
- Modified `manager_backend/api.py`
  - Registered the portability router.
- Created `tests/manager/test_profile_portability.py`
  - 19 focused tests covering the task requirements and review regressions.
- Created `.superpowers/sdd/portability-task-1-report.md`
  - This report.

## Self-review

- Export schema has stable field order, sorted tags and permission keys, and exact format/version values.
- Export omits database IDs, timestamps, runtime state/logs, profile/download paths, fingerprint identity, proxy credentials, cookies, diagnostics, and session/license material.
- Proxy export includes only scheme/host/port; import always leaves `proxy_id` unset and returns a bounded generic warning.
- Import creates or reuses folders, statuses, and tags using whitespace-normalized case-insensitive names without overwriting existing catalog colors.
- Name suffixes are deterministic and length-bounded: ` (imported 1)`, ` (imported 2)`, and so on.
- Import performs one commit after all database rows and the new profile directory are ready. All failure paths roll back, and cleanup removes only a directory successfully created by this import.
- Request input is consumed incrementally and rejected before accumulating more than 2 MiB; invalid-document errors contain field paths, never request content.
- The filename is ASCII-sanitized before entering `Content-Disposition`; downloads also use `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.
- Independent review reported two Important findings (unbounded body buffering and coercive nested types). Both were fixed with RED/GREEN regressions; re-review reported no remaining issues.
- Existing PATCH/runtime code and unrelated dirty SDD coordination files were not changed or staged.

## Concerns / follow-on

- Export currently emits `extensions: []` because extension persistence/assignments do not exist until plan Task 4. `_export_extensions()` is an explicit integration seam; Task 4 must populate it with manifest metadata only, never IDs or paths. Import already accepts strict extension metadata and emits one safe missing-extension warning per unresolved reference.
- Static `manager_backend/openapi.json` regeneration is intentionally deferred to the plan's Task 7 contract gate.
