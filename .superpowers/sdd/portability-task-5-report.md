# Portability Task 5 Report

## Outcome

Implemented Manager runtime loading for enabled, assigned unpacked extensions.

- Runtime queries the `profile_extensions` join at profile start, so disabled,
  unassigned, and unregistered extensions are omitted.
- Every selected registration is revalidated through the existing canonical-path
  and handle-based manifest reader. A changed manifest or unsafe path fails before
  a runtime row or browser worker is created.
- Canonical paths are sorted by `(casefolded path, path)` and copied into the
  immutable launch snapshot.
- The launch adapter passes paths only through CloakBrowser's supported
  `extension_paths` option. It does not build a command string or add extension
  switches to Manager-owned Chromium arguments, and snapshot-supplied arguments
  cannot replace the Manager fingerprint flag.
- The POSIX manifest descriptor now includes `O_NONBLOCK`, preventing a replaced
  FIFO from blocking before the regular-file check. Directory traversal flags are
  unchanged.

## TDD evidence

RED:

```text
python -m pytest <five new focused cases> -q
5 failed
```

The failures showed that `extension_paths` was absent, assigned extensions were
ignored, changed manifests did not stop launch, and POSIX manifest open omitted
`O_NONBLOCK`.

GREEN and regression gates:

```text
python -m pytest tests/manager/test_runtime_manager.py tests/manager/test_extension_filesystem.py -q
30 passed, 1 warning

python -m pytest tests/manager/test_runtime_manager.py tests/manager/test_runtime_api.py tests/manager/test_cookie_api.py tests/manager/test_extensions_api.py tests/manager/test_extension_filesystem.py tests/test_extension_loading.py tests/test_persistent_context.py -q
95 passed, 1 skipped, 1 warning

python -m pytest tests/manager -q
358 passed, 3 skipped, 1 warning

python -m compileall -q manager_backend
exit 0
```

The broader gate initially exposed one cookie-adapter compatibility regression:
an empty `extension_paths` option was forwarded to cookie-only launches. It was
corrected by emitting the wrapper option only for a nonempty runtime path list.

The warning is the pre-existing Starlette deprecation warning for importing
`httpx` through `fastapi.testclient`.

## Files changed

- `manager_backend/features/runtime/launcher.py`
- `manager_backend/features/runtime/manager.py`
- `manager_backend/features/extensions/service.py`
- `manager_backend/features/extensions/filesystem.py`
- `tests/manager/test_runtime_manager.py`
- `tests/manager/test_extension_filesystem.py`

## Residual boundary

CloakBrowser's supported extension interface accepts filesystem path strings, not
open directory handles. Manager therefore revalidates canonical identity and the
manifest through secured handles immediately before snapshot creation and fails
closed on mismatch, but it cannot pin the directory identity through Chromium's
later consumption of that path. Eliminating that final external-consumer race
would require a different browser/wrapper interface.
