# Task 4: Safe profile-directory operations

## Scope

Added manager-owned profile-directory resolution and the authenticated `POST /api/v1/profiles/{profile_id}/open-directory` action. Profile read responses now include the display-safe absolute directory path. No frontend files were changed.

## RED

Added `tests/manager/test_profile_directories.py` before implementation, covering derived canonical paths, traversal/noncanonical IDs, escaped symlinks, directory creation, an injected opener, non-Windows rejection, and sanitized operating-system errors. Added the API assertion for `ProfileRead.profile_directory`.

Command:

```powershell
python -m pytest tests/manager/test_profile_directories.py tests/manager/test_profiles_api.py -q
```

Observed result: collection failed with the expected `ModuleNotFoundError: No module named 'manager_backend.features.profiles.directories'` before any directory implementation existed.

## GREEN

- `resolve_profile_directory()` requires the canonical UUID form, derives only `<data_root>/profiles/<profile-id>`, resolves the data root, profile root, and target, and verifies containment before returning a path.
- `open_profile_directory()` creates that resolved path, invokes an injectable opener (Windows Explorer by default), rejects non-Windows hosts, and returns `directory_open_failed` without operating-system text.
- The route loads the profile before resolving/opening it, so request input never controls a filesystem path; global API authentication, Origin, and CSRF mutation rules remain in force.
- `ProfileRead` and the open-directory response expose `profile_directory`; profile serialization receives app settings rather than a caller-supplied path.
- Regenerated `manager_backend/openapi.json` for the updated contract.

Focused verification:

```powershell
python -m pytest tests/manager/test_profile_directories.py tests/manager/test_profiles_api.py -q
```

Result: `22 passed, 1 skipped, 1 warning`.

Full Manager verification:

```powershell
python -m pytest tests/manager -q
```

Result: `184 passed, 2 skipped, 1 warning`.

## Files

- Created: `manager_backend/features/profiles/directories.py`
- Created: `tests/manager/test_profile_directories.py`
- Modified: `manager_backend/features/profiles/routes.py`
- Modified: `manager_backend/features/profiles/schemas.py`
- Modified: `manager_backend/features/profiles/service.py`
- Modified: `tests/manager/test_profiles_api.py`
- Modified: `manager_backend/openapi.json`

## Self-review

- No client request field supplies or influences the directory path.
- Canonical UUID validation rejects traversal-like and alternate UUID encodings before filesystem work.
- Resolved containment detects profile-directory and profile-root symlink escapes.
- Explorer failures use stable Manager error codes and omit raw OS messages.
- The endpoint remains inside the existing authenticated mutation router; no frontend or push action was performed.

## Concerns

The escaped-symlink regression is skipped only on Windows installations that lack symlink-creation privilege (this environment returned WinError 1314). The production containment check is present and the other focused tests pass. The suite retains the existing Starlette TestClient deprecation warning.
