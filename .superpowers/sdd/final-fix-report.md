# Final fix report — feat/signup-trial review fixes

## Status
DONE

## Commit
`c59c8c4077f198da257858fda816dc8aa08b8c3d` — `fix(cloud): scope trial_end to trial-plan keys + review cleanups`
(local only, on `feat/signup-trial`; not pushed)

## Test summary
```
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pytest tests/cloud/test_licensing.py tests/cloud/test_signup.py tests/manager/test_account.py tests/manager/test_license.py -v
```
Result: **41 passed**, 1 unrelated deprecation warning (httpx/starlette TestClient), 0 failed.

- `tests/cloud/test_licensing.py` — 16 passed (incl. new `test_expiring_non_trial_key_has_no_trial_end`, adapted `test_expiring_key_stamps_trial_end_claim`)
- `tests/cloud/test_signup.py` — 5 passed, unchanged
- `tests/manager/test_account.py` — 8 passed (incl. new `test_routes_register_reflects_in_license`)
- `tests/manager/test_license.py` — 12 passed, unchanged

## FIX 1 — trial_end scoping

**Root cause confirmed:** `cloud/licensing.py::_issue_entitlement` stamped
`trial_end=ensure_aware_utc(key.expires_at)` for *any* key with an `expires_at`,
regardless of plan — so a paid Pro key issued with `--expires-days 365` would get
the trial hard-cap claim, forcing `expired` state in
`manager_backend/features/license/service.py::evaluate_license` at expiry and
skipping the 7-day offline grace entirely.

**Constant location:** `TRIAL_PLAN_ID = "trial"` now lives in `cloud/licensing.py`
(added near the top, right after `ENTITLEMENT_VERSION`). Verified no circular
import: `licensing.py`'s only local imports are `. import models`,
`.db`, `.entitlements`, `.keys` — none touch `cloud.features.auth` or
`cloud.admin`. Confirmed by running
`python -c "import cloud.licensing; import cloud.features.auth.service"`
successfully. `cloud/features/auth/service.py` now does
`from ...licensing import TRIAL_PLAN_ID, redeem_key` and the local
`TRIAL_PLAN_ID = "trial"` definition was removed. No other module referenced
`auth.service.TRIAL_PLAN_ID` (grepped the whole repo — only `cloud/admin.py`
imports `auth.service as auth` and it never touched that constant).

**Fix applied:**
```python
trial_end=ensure_aware_utc(key.expires_at) if plan.id == TRIAL_PLAN_ID else None,
```

**Test adaptation:** `_setup()` in `tests/cloud/test_licensing.py` gained a
`plan_id="pro"` kwarg (default preserves every existing test's behavior — plan id
"pro", `claims["plan"] == "pro"` assertions untouched).
- `test_expiring_key_stamps_trial_end_claim` now calls
  `_setup(session_factory, expires_at=expires_at, plan_id=TRIAL_PLAN_ID)` so the
  redeemed key is genuinely on the trial plan — still asserts
  `trial_end == expires_at.timestamp()`.
- Added `test_expiring_non_trial_key_has_no_trial_end`: an expiring key on the
  default (non-trial, "pro") plan → asserts `"trial_end" not in result.claims`.
- `test_non_expiring_key_has_no_trial_end` left untouched.
- `tests/cloud/test_signup.py` was **not modified** — `signup_trial` redeems a
  key created via `issue_key(plan_id=TRIAL_PLAN_ID, ...)`, so `plan.id ==
  TRIAL_PLAN_ID` still holds and `trial_end` is still stamped; both signup tests
  that assert on `trial_end`/`claims["plan"] == "trial"` still pass unmodified.

## FIX 2 — cosmetic cleanups
- `cloud/features/auth/routes.py`: removed the unused `request: Request`
  parameter from the `signup` handler. Kept the `Request` import — `register`,
  `token`, and `password_reset_request` handlers in the same file still use
  `request.app.state.*`.
- `manager_backend/features/license/service.py`: added a line to the module
  docstring's state-machine section: "A past `trial_end` claim (trial-plan keys
  only) forces `expired` regardless of `exp`/`offline_grace_deadline` — the
  trial hard-cap always wins."

## FIX 3 — missing route-level test
Added `test_routes_register_reflects_in_license` to `tests/manager/test_account.py`,
placed immediately before `test_register_creates_trial_and_unlocks` and mirroring
`test_routes_login_activate_reflect_in_license` exactly: builds the app via
`manager_backend.main.create_app`, overwrites `client.app.state.account_service`
with an `AccountService` wired to the fake-cloud-backed `CloudClient`, does the
`/api/v1/auth/setup` CSRF dance, then `POST /api/v1/account/register` with
`{email, password}` and asserts `200` + `state == "active"`, followed by
`GET /api/v1/license` reporting `state == "active"`.

## openapi.json
No changes — `git status --porcelain manager_backend/openapi.json` is clean.
Expected: `signup` lives in `cloud`, not `manager_backend`, and the removed
`request` param carries no schema footprint (FastAPI `Request` params never
appear in the OpenAPI schema regardless). No hand-edit was made or needed.

## Scope discipline
Only 6 files touched and staged: `cloud/licensing.py`,
`cloud/features/auth/service.py`, `cloud/features/auth/routes.py`,
`manager_backend/features/license/service.py`, `tests/cloud/test_licensing.py`,
`tests/manager/test_account.py`. Pre-existing unrelated working-tree changes
(`.impeccable/hook.cache.json`, `.superpowers/sdd/task-*` files, a deleted
`Velas Component Colors.dc.html`) were left untouched and unstaged, per
instructions. Signup-throttling and `register_device`'s `platform` item were
left as-is (explicitly out of scope).

## Concerns
None. All four required suites pass; the scoping fix is minimal and localized;
no circular import; the docstring/test additions are consistent with the
codebase's existing style and fixtures.
