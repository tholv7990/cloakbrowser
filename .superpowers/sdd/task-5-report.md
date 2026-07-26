# Task 5 Report: Desktop — register bridge (client + service + schema + route)

## Status: DONE

Note: this path previously held a report for an unrelated, concurrently-running "Task 5" from a
different SDD cycle (frontend monitors/arrangeWindows API surface, branch
`feat/synchronize-window-tiling`). That content is superseded here per this task's brief
instruction to write to this exact path; retrieve it via
`git log -p -- .superpowers/sdd/task-5-report.md` if needed.

## Pre-implementation verification

Before transcribing the brief's code, verified all referenced pieces against the real repo:

- `manager_backend/features/account/cloud_client.py`: `login()` and `_post()` match the brief's
  description exactly; `DeviceIdentity` is already imported at module top (`from .device import
  DeviceIdentity`), so `register()` needed no new import.
- `manager_backend/features/account/service.py`: `login()`/`activate()`, `REFRESH_REF`,
  `get_or_create_device`, `_manager_error`, `_CLOUD_ERRORS` all present and match.
- `manager_backend/features/account/schemas.py`: `LoginRequest` matches the mirror pattern.
- `manager_backend/features/account/routes.py`: `LicenseStatusRead` import and route pattern match.
- `tests/manager/test_account.py`: `cloud` fixture builds a real in-process cloud app via
  `create_cloud_app` — the same app that serves `/auth/signup` (added in Tasks 1-3). It pins a
  seeded Pro plan/key for the login+activate tests but does not limit which routes are reachable,
  so `register()` (which mints its own trial via `/auth/signup`) needs no seeded key.
- `cloud/features/auth/routes.py` + `cloud/features/auth/service.py`: confirmed `POST /auth/signup`
  returns `SignupResponse(access_token, refresh_token, expires_in, entitlement_token)`, and
  `signup_trial()` raises `AuthError("email_taken")` on a duplicate email (via `IntegrityError` on
  user insert), which `cloud/errors.py` maps to HTTP 409 with body `{"error": "email_taken"}`.
  This is exactly what `CloudClientError` surfaces to the service layer. No adaptation needed —
  the brief's code was correct as written.

## TDD

### RED

Appended the two tests from the brief to `tests/manager/test_account.py` (verbatim, per the brief).

Command: `& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pytest tests/manager/test_account.py -k register -v`

Result: 2 failed as expected:
```
tests/manager/test_account.py::test_register_creates_trial_and_unlocks FAILED
tests/manager/test_account.py::test_register_duplicate_email_is_safe_error FAILED
...
E       AttributeError: 'AccountService' object has no attribute 'register'
```
(same AttributeError for both tests)

### GREEN

Implemented exactly per brief:
- `CloudClient.register(*, email, password, device)` in `cloud_client.py`, added after `login()`.
- `AccountService.register(*, email, password)` in `service.py`, added after `login()`; added
  `"email_taken": ("An account with this email already exists.", 409)` to `_CLOUD_ERRORS`.
- `RegisterRequest` in `schemas.py` (`email: EmailStr`, `password: Field(min_length=12,
  max_length=1024)`), added after `LoginRequest`.
- `POST /account/register` in `routes.py` (imports `RegisterRequest`, added between `login` and
  `activate`).

Command: `& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pytest tests/manager/test_account.py -v`

Result: 7 passed (all pre-existing account tests + the 2 new ones).

Command: `& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pytest tests/manager -q`

First run surfaced 1 unrelated regression: `test_openapi_static.py::
test_checked_in_openapi_matches_generated_application_contract` — the checked-in
`manager_backend/openapi.json` contract diverged because the new `/account/register` route wasn't
reflected in it. This is a generated artifact (`manager_backend/export_openapi.py`), not called
out in the brief, but the prior login/activate task's commit (`3ab4920`) also touched
`openapi.json` for the same reason, so I followed the same precedent. Regenerated it with:

`& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m manager_backend.export_openapi`

Re-ran the full suite: 795 passed, 5 skipped (skips are pre-existing/unrelated), 0 failures.

## Files changed

- `manager_backend/features/account/cloud_client.py` — added `register()`.
- `manager_backend/features/account/service.py` — added `register()`, added `"email_taken"` to
  `_CLOUD_ERRORS`.
- `manager_backend/features/account/schemas.py` — added `RegisterRequest`.
- `manager_backend/features/account/routes.py` — added `RegisterRequest` import + `POST /register`.
- `manager_backend/openapi.json` — regenerated (adaptation beyond the brief; see above).
- `tests/manager/test_account.py` — appended the two tests from the brief.
- `.superpowers/sdd/task-5-report.md` — this report (overwrote unrelated concurrent-cycle content).

## Adaptations from the brief

1. Regenerated and committed `manager_backend/openapi.json`. The brief's `git add` list didn't
   mention it, but without it `tests/manager/test_openapi_static.py` fails — a real regression
   caused by adding the route, not a pre-existing one — and the precedent commit for the
   login/activate route (`3ab4920`) updated the same file the same way. Staged only the four
   account files + this generated file + the test file, keeping to the spirit of the brief's scope
   instruction (did not touch the many other unrelated modified files sitting in the working tree
   from other concurrent SDD tasks — `.superpowers/sdd/task-1..6-*`, `progress.md`, etc.).

No other deviations — the brief's code for `cloud_client.py`, `service.py`, `schemas.py`, and
`routes.py` was transcribed verbatim and worked first try.

## Self-review

- Register stores the session AND installs the entitlement: confirmed —
  `self._secrets.put(REFRESH_REF, ...)`, `self._save_state({"email": email})`, then
  `license_service.install_entitlement(...)` is returned, in that order, matching `login()` +
  `activate()`'s combined effect.
- On cloud failure nothing partial is stored: confirmed — `client.register(...)` is the only
  statement inside the `try`; a `CloudClientError` raises `_manager_error(error)` before any of
  `_secrets.put`, `_save_state`, or `install_entitlement` run. No partial state possible.
- `email_taken` mapped: confirmed — `_CLOUD_ERRORS["email_taken"]` -> message + 409, and
  `_manager_error` prefixes to `cloud_email_taken`, matching
  `test_register_duplicate_email_is_safe_error`'s assertion.

## Concerns

- No route-level (HTTP, via `TestClient`) test exercises `POST /api/v1/account/register` or the
  `RegisterRequest` min_length=12 validation directly — the brief's two tests only exercise
  `AccountService.register()` at the service layer (same scope as the brief specified; the
  existing `test_routes_login_activate_reflect_in_license` route-level test wasn't extended for
  register). Minor coverage gap, not a functional concern — the route is a thin pass-through
  identical in shape to `activate`'s route, which is covered at the route level.
- The working tree has many unrelated modified/deleted files from other concurrent work
  (`.superpowers/sdd/task-1..6-*`, `progress.md`, `.impeccable/hook.cache.json`, a deleted
  `Velas Component Colors.dc.html`). None of these were touched or staged by this task.

## Commit

`d6b7dfd` — `feat(account): register bridge -> cloud signup + install trial entitlement`
(local commit on `feat/signup-trial`, not pushed).

Files changed: 6 files, 160 insertions(+), 1 deletion(-)
- `manager_backend/features/account/cloud_client.py`
- `manager_backend/features/account/routes.py`
- `manager_backend/features/account/schemas.py`
- `manager_backend/features/account/service.py`
- `manager_backend/openapi.json`
- `tests/manager/test_account.py`
