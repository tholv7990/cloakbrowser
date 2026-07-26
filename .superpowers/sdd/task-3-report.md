# Task 3 Report: Cloud — `POST /auth/signup` route + schemas

**Status: DONE**

## Summary

Exposed Task 2's `signup_trial(...)` / `SignupResult` over HTTP: added
`SignupRequest`/`SignupResponse` to `cloud/schemas.py` and a `POST /auth/signup`
handler to `cloud/features/auth/routes.py`, mirroring the existing `/auth/token`
handler's dependency injection and error pattern exactly. TDD followed: RED
(404) confirmed before implementation, GREEN confirmed after, full `tests/cloud`
suite re-run to check for regressions.

## Verification performed before transcribing (per task instructions)

- Read `cloud/features/auth/routes.py` — confirmed `devices` (as `service as
  devices`) and `CloudError` are already imported and used by `token`; confirmed
  `token`'s exact DI pattern (`Depends(get_session)`, `Depends(get_settings)`,
  `request: Request` parameter present in `token`'s signature).
- Read `cloud/app.py` — `create_app(settings, *, session_factory=None,
  email_sender=None)` matches the test's `_app()` helper call exactly.
- Read `cloud/licensing.py` — `RedeemError` is a top-level class (line 54),
  importable as `from ...licensing import RedeemError`.
- Read `cloud/errors.py` — `STATUS` dict already maps `email_taken: 409`,
  `invalid_key: 404`, `key_revoked/key_suspended/key_expired: 403`,
  `key_exhausted: 409`, `redeem_conflict: 409`, `plan_missing: 500`. No changes
  needed there.
- Read `cloud/features/auth/service.py` (Task 2 output) — `signup_trial` and
  `SignupResult` already present and match the brief's call signature
  (`email`, `password`, `device_public_key`, `device_signature`, `device_name`,
  `settings`).
- Listed `tests/cloud/` — no OpenAPI/contract snapshot test exists, so no
  regeneration step was needed.

The brief's code matched the real patterns with no conflicts — nothing to
adapt functionally.

## TDD: RED

Appended the three API-level tests (`test_signup_endpoint_*`) from the brief to
`tests/cloud/test_signup.py`, reusing the existing `session_factory` fixture and
`_device()` helper. Moved the new imports (`TestClient`, `create_app`,
`RecordingEmailSender`) to the top of the file alongside the existing imports
instead of mid-file (the brief showed them appended just before `_app()`) —
pure style cleanup, no behavior change.

Command:
```
& "$LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pytest tests/cloud/test_signup.py -k endpoint -v
```

Output (abridged):
```
FAILED tests/cloud/test_signup.py::test_signup_endpoint_returns_session_and_trial_entitlement
    AssertionError: {"detail":"Not Found"}
    assert 404 == 200
FAILED tests/cloud/test_signup.py::test_signup_endpoint_rejects_short_password
    assert 404 == 422
FAILED tests/cloud/test_signup.py::test_signup_endpoint_duplicate_email
    AssertionError: assert 404 == 200
3 failed, 2 deselected, 1 warning in 0.97s
```
Confirms the route did not exist yet — exactly as expected.

## Implementation

`cloud/schemas.py` — added `SignupRequest` (email, password min_length=12,
device_public_key, device_signature, device_name default "Plasma Desktop") and
`SignupResponse` (access_token, refresh_token, token_type="bearer",
expires_in, entitlement_token), placed after `TokenRequest`, verbatim per the
brief.

`cloud/features/auth/routes.py` — added `from ...licensing import RedeemError`,
extended the schema import block with `SignupRequest, SignupResponse`, and
added the `signup` handler between `token` and `refresh`:

```python
@router.post("/signup", response_model=SignupResponse)
def signup(
    body: SignupRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: CloudSettings = Depends(get_settings),
) -> SignupResponse:
    try:
        result = auth.signup_trial(
            session,
            email=body.email,
            password=body.password,
            device_public_key=body.device_public_key,
            device_signature=body.device_signature,
            device_name=body.device_name,
            settings=settings,
        )
    except (auth.AuthError, devices.DeviceError, RedeemError) as error:
        raise CloudError(error.code) from error
    return SignupResponse(
        access_token=result.tokens.access_token,
        refresh_token=result.tokens.refresh_token,
        expires_in=int(settings.access_ttl.total_seconds()),
        entitlement_token=result.entitlement_token,
    )
```

## TDD: GREEN

Command:
```
& "$LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pytest tests/cloud/test_signup.py -v
```
Output:
```
tests/cloud/test_signup.py::test_signup_creates_active_user_trial_key_and_entitlement PASSED
tests/cloud/test_signup.py::test_signup_duplicate_email_rejected PASSED
tests/cloud/test_signup.py::test_signup_endpoint_returns_session_and_trial_entitlement PASSED
tests/cloud/test_signup.py::test_signup_endpoint_rejects_short_password PASSED
tests/cloud/test_signup.py::test_signup_endpoint_duplicate_email PASSED
5 passed, 1 warning in 1.52s
```

Full cloud suite:
```
& "$LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pytest tests/cloud -q -rs
```
Output:
```
96 passed, 3 skipped, 1 warning in 12.80s
SKIPPED [3] tests\cloud\test_postgres_concurrency.py: set CLOUD_TEST_DATABASE_URL to a PostgreSQL DSN to run the concurrency suite
```
The 3 skips are pre-existing (require a live Postgres DSN) and unrelated to
this change — no new skips or failures introduced. No OpenAPI/contract
snapshot test present in `tests/cloud/`, so nothing needed regenerating.

## Self-review (against the brief's checklist)

- **200 returns access/refresh/entitlement** — `test_signup_endpoint_returns_session_and_trial_entitlement`
  asserts `body["access_token"]`, `body["refresh_token"]` truthy and
  `body["entitlement_token"]` is a verifiable signed token.
- **Entitlement verifies plan=trial + trial_end** — same test:
  `verify_entitlement(...)` then `claims["plan"] == "trial"` and
  `"trial_end" in claims`.
- **Short password → 422** — `password: str = Field(min_length=12, ...)` on
  `SignupRequest` triggers Pydantic validation before the handler runs;
  `test_signup_endpoint_rejects_short_password` confirms 422.
- **Duplicate email → 4xx `{"error":"email_taken"}`** —
  `test_signup_endpoint_duplicate_email` confirms status ≥ 400 (409, per
  `cloud/errors.py`'s existing `STATUS` map) and `resp.json()["error"] ==
  "email_taken"`.

## Files changed

- `cloud/schemas.py` — `SignupRequest`, `SignupResponse` added (19 lines).
- `cloud/features/auth/routes.py` — `signup` route + imports added (30 lines).
- `tests/cloud/test_signup.py` — 3 new API-level tests + imports appended (51 lines).

## Concerns / adaptations

- None blocking. Only adaptation: relocated the test file's new imports to the
  top of the file (with the rest of the module's imports) instead of inline
  mid-file, for style consistency — no functional difference, brief's test
  bodies transcribed verbatim.
- `request: Request` is accepted by `signup` but unused inside the handler
  body (unlike `token`, which uses it for `request.app.state.session_factory`
  to enforce login throttling). Kept it per the brief to mirror `token`'s
  signature shape; signup has no login-throttle requirement since it's
  one-time account creation, not a repeatable credential-guessing surface.
  No lint config in the repo flags unused parameters (no ruff/flake8 config
  found), so this is cosmetic only, not a functional gap.

## Commit

Local commit on `feat/signup-trial` (not pushed): `6ae563c` —
"feat(cloud): POST /auth/signup endpoint". Staged only
`cloud/schemas.py`, `cloud/features/auth/routes.py`,
`tests/cloud/test_signup.py` — other unrelated pre-existing working-tree
changes in the repo were left untouched.

## Note

This file previously contained an unrelated report ("Task 3: Real Win32
`WindowManager`", for `manager_backend`'s runtime window-tiling work — a
different feature's Task 3 sharing this same path). That content has been
replaced above per this task's brief, which directs the sign-up feature's
Task 3 report to this exact path.
