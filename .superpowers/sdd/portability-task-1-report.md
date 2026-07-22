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

## Approved strict-contract follow-up

### Additional RED evidence

- Required discriminators: documents missing `format` or `version` validated because both fields had defaults.
- Machine extension IDs: `chrome-extension://<machine-id>/...` startup URLs exported and reimported verbatim.
- Permission/error bounds: permission maps had no entry/key bounds, and validation locations reflected attacker-controlled keys without an error-count cap.
- Trusted settings: `import_profile(session, document)` allowed directory creation to be silently skipped.
- Concurrent resolution: two simultaneous imports could check the same catalog/profile-name state before either committed; catalog lookups also scanned whole tables once per reference.
- Deterministic ties: casefold-equivalent tag/catalog names lacked original-name and stable-ID tie-breakers.
- Cleanup: no regression covered a directory successfully created before a later commit failure.

Each item received a failing focused test or adversarial/concurrent regression before the implementation change. The legacy oversized-permissions export regression also failed before deterministic filtering was added.

### Additional GREEN evidence

- `ProfileExportV1` now requires explicit `format` and `version`; export supplies the exact v1 constants.
- Portable export/import removes all `chrome-extension://` startup URLs. HTTP export emits only the fixed `chrome_extension_startup_urls_skipped` warning code; import emits one bounded generic warning and never reflects the machine ID.
- Portable permissions accept at most 64 entries with keys of at most 80 characters. Legacy export maps are deterministically sorted, filtered, and capped.
- Validation conversion returns at most 16 fixed `invalid` entries, maps indices/unknown keys to safe fixed path components, and does not include file values. A 200-key/200-extra-field adversarial request produced a response below 2 KiB with no marker/content reflection.
- The service interface is now `import_profile(session, settings, document)`; trusted settings are mandatory and every successful import creates its manager-owned directory.
- Import executes `BEGIN IMMEDIATE` before all resolution reads, so SQLite serializes the complete check-and-write transaction. No normalized-key migration is needed, avoiding destructive handling of existing case-variant duplicates.
- Folder/status/tag tables and profile names are each loaded once into deterministic normalized indexes. Legacy duplicates resolve by normalized name, original name, then stable ID; incoming/exported tags sort by normalized name, original name, then color.
- `OperationalError` and `IntegrityError` map to fixed typed errors without database detail. A directory created before a simulated commit `IntegrityError` is removed after rollback; a pre-existing directory remains untouched.
- Focused: `python -m pytest tests/manager/test_profile_portability.py -q` -> `33 passed, 1 warning in 3.06s`.
- Concurrent stress: simultaneous normalized-catalog/name import regression repeated 10 times -> `10/10 passed`.
- Full Manager: `python -m pytest tests/manager -q` -> `243 passed, 2 skipped, 1 warning in 32.19s`.
- Compile and scoped diff checks exited 0.

### Follow-up review

- The approved contract required an equally enforced database design rather than necessarily persistent normalized columns. SQLite writer reservation is the chosen compatibility-safe enforcement: it protects concurrent imports while preserving deterministic lookup of existing case-variant duplicates.
- Extension assignment/export remains the Task 4 integration seam and must use manifest metadata only. Machine extension IDs are no longer portable through startup URLs.
- Independent strict review found that raw prefix matching could miss whitespace/control-prefixed extension URLs accepted by `urlsplit`. A RED regression reproduced the leak; filtering now uses the parsed, case-normalized scheme, and raw plus space/tab-prefixed cases pass without ID reflection.
- Independent strict review also found that all `OperationalError` values were classified as lock contention. A RED regression split the cases: only SQLite `BUSY`/`LOCKED` base error codes now map to retryable `profile_import_busy`/409; other operational failures map to safe `profile_import_failed`/500.
- Python 3.9/3.10 compatibility is covered with an exact match for SQLite's fixed lock messages when `sqlite_errorcode` is unavailable; unknown messages remain non-retryable 500 errors.
- The review noted that loading each catalog/profile-name table once is O(total manager data) while the SQLite writer reservation is held. This is the explicitly approved alternative to normalized persistent columns and avoids a compatibility migration for existing case-variant duplicates; a future scale-driven schema change may add normalized indexed keys with an explicit duplicate policy.
