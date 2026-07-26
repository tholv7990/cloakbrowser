# Task 2 Report: Cloud — `signup_trial` service

## Status: DONE

## TDD cycle

### RED

Created `tests/cloud/test_signup.py` verbatim per the brief (2 tests:
`test_signup_creates_active_user_trial_key_and_entitlement`,
`test_signup_duplicate_email_rejected`).

```
$ python -m pytest tests/cloud/test_signup.py -v
...
ImportError while importing test module '...\tests\cloud\test_signup.py'.
tests\cloud\test_signup.py:14: in <module>
    from cloud.features.auth.service import AuthError, signup_trial
E   ImportError: cannot import name 'signup_trial' from 'cloud.features.auth.service'
=========================== short test summary info ===========================
ERROR tests/cloud/test_signup.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

Matches the brief's expected failure exactly.

### GREEN

Implemented `TRIAL_PLAN_ID`, `TRIAL_DAYS`, `ensure_trial_plan`, `SignupResult`,
and `signup_trial` in `cloud/features/auth/service.py`, inserted between
`verify_email` and the `# --- authentication ---` section (logically grouped
with account creation).

```
$ python -m pytest tests/cloud/test_signup.py -v
tests/cloud/test_signup.py::test_signup_creates_active_user_trial_key_and_entitlement PASSED
tests/cloud/test_signup.py::test_signup_duplicate_email_rejected PASSED
============================== 2 passed in 0.67s ==============================
```

### Full `tests/cloud` regression check

```
$ python -m pytest tests/cloud -q
........................................................................ [ 75%]
.......sss..............                                                [100%]
93 passed, 3 skipped, 1 warning in 12.46s
```

The 3 skips are `test_postgres_concurrency.py` (require a live Postgres —
pre-existing, unrelated to this change).

## Cross-module signature verification (done before transcribing)

Read the real source for every dependency the brief names, rather than
trusting its inlined signatures:

- `register_device` (`cloud/features/devices/service.py:48`) — keyword params
  are exactly `user`, `public_key_b64`, `challenge`, `signature_b64`, `name`
  (+ optional `platform`, `now`), matching the brief precisely. No adaptation
  needed. Confirmed `verify_device_possession` verifies `signature_b64` over
  `challenge.encode("utf-8")`, so the test's `f"plasma-device:{public_b64}"`
  challenge string is byte-identical to what `signup_trial` builds
  (`f"plasma-device:{device_public_key}"`).
- `issue_key` (`cloud/admin.py:31`) — signature matches the brief exactly:
  `session, *, plan_id, pepper, max_uses=1, expires_at=None, created_by="admin"`
  → `(display_key, models.ActivationKey)`.
- `redeem_key` (`cloud/licensing.py:148`) — signature matches the brief
  exactly: `session, *, raw_key, user_id, device_id, pepper, private_key, now,
  ttl, grace` → `RedeemResult` (has `.token`, confirmed by reading
  `RedeemResult`'s definition and other call sites in `licensing.py`).
- `create_session`, `IssuedTokens`, `AuthError`, `normalize_email`,
  `hash_password` — already present/imported in `cloud/features/auth/service.py`
  as the brief assumed; no changes needed there.
- `models.User` — `CheckConstraint("status in ('unverified','active','suspended')")`
  confirmed in `cloud/models.py:64-66`, so `status="active"` at creation is valid.
- `models.Plan` — fields `id, name, max_devices, max_profiles, max_sessions,
  features` all match what `ensure_trial_plan` constructs.

## Circular-import finding (adapted from the brief as instructed)

The brief's Step 3 code as written places `from ...admin import issue_key` as
a **top-level** module import in `cloud/features/auth/service.py`. This is
unsafe: `cloud/admin.py` already imports this exact module at its own top
level (`cloud/admin.py:27`: `from .features.auth import service as auth`).
Two modules importing each other at module scope is only safe if neither
import path ever asks the other, while it's still mid-initialization, for a
name that hasn't been defined yet — and here it can: if `cloud.admin` is the
*first* of the two to be imported anywhere in the process, executing
`admin.py` up to line 27 triggers the import of
`cloud.features.auth.service`, which (with a top-level `from ...admin import
issue_key`) then tries to pull `issue_key` out of `cloud.admin` while that
module is still mid-import (only through line 26, `issue_key` is defined at
line 31) → `ImportError: cannot import name 'issue_key' from partially
initialized module 'cloud.admin' (most likely due to a circular import)`.

This isn't hypothetical: `tests/cloud/test_admin.py` does
`from cloud.admin import issue_key, ...` and sorts alphabetically before
`test_signup.py`, so running the **full** `tests/cloud` suite hits this path
via pytest's collection order (test_admin.py collected first → cloud.admin
imported first).

**Verified empirically** (not just reasoned about): temporarily moved the
import to top-level and ran `python -c "import cloud.admin"` in a fresh
process — it reproduced the exact `ImportError` above. Reverted, then
confirmed `python -c "import cloud.admin"` succeeds cleanly with the import
deferred inside `signup_trial()`'s function body (Python resolves
`create_session`, `redeem_key`, `register_device`, and now `issue_key` at
*call* time, by which point both modules have finished loading regardless of
which was imported first).

**Fix applied**: `from ...admin import issue_key` is imported lazily at the
top of `signup_trial`'s body, with a comment explaining why. `redeem_key`
(from `cloud/licensing.py`) and `register_device` (from
`cloud/features/devices/service.py`) were safe to import at module level —
neither of those modules imports `cloud.features.auth.service`, so there is
no cycle for them.

## Self-review checklist

- Active user: `status="active"` set at creation, no `EmailVerification` row
  created (unlike `register_user`) — confirmed by the test asserting
  `user.status == "active"` immediately after `signup_trial`, with no
  separate `verify_email` call.
- `trial_end == now + 30d` in the entitlement: confirmed by
  `test_signup_creates_active_user_trial_key_and_entitlement` asserting
  `claims["trial_end"] == int((NOW + timedelta(days=30)).timestamp())` — this
  flows from Task 1's `_issue_entitlement`/`redeem_key` stamping `trial_end`
  from the key's `expires_at`, which `signup_trial` sets to
  `now + timedelta(days=trial_days)` when calling `issue_key`.
- Duplicate email → `AuthError("email_taken")`: confirmed by
  `test_signup_duplicate_email_rejected`; same `IntegrityError`-catch pattern
  as `register_user`.
- No circular import: verified empirically both ways (see above) — the full
  `tests/cloud` suite (93 passed, 3 skipped) exercises the real import order
  including `test_admin.py` first.
- `result.tokens.refresh_token` truthy (a session was minted): confirmed by
  the same test.

## Files changed

- `cloud/features/auth/service.py` — added `TRIAL_PLAN_ID`, `TRIAL_DAYS`,
  `ensure_trial_plan`, `SignupResult`, `signup_trial`; added module-level
  imports `timedelta`, `redeem_key`, `register_device`; added a
  function-local lazy import of `issue_key`.
- `tests/cloud/test_signup.py` — new, verbatim per the brief.

## Commit

`ff45097` — `feat(cloud): signup_trial service (active user + 30-day trial + redeem)`
(local only, on `feat/signup-trial`, not pushed). Staged only the two files
above; other unrelated working-tree changes present in the repo (other
tasks' briefs/reports, `.impeccable/hook.cache.json`, a deleted `.dc.html`
file) were left untouched and unstaged.

## Concerns

None blocking. Worth flagging for whoever reviews the branch as a whole: the
lazy-import pattern for `issue_key` is a workaround for a pre-existing
architectural circularity between `cloud/admin.py` and
`cloud/features/auth/service.py` (admin already depended on auth.service for
`revoke_all_sessions`; now auth.service also depends on admin for
`issue_key`). It works and is tested, but if a future change adds more
admin-side dependencies into `signup_trial` or elsewhere in `service.py`,
the same lazy-import treatment will be needed. A cleaner long-term fix would
be extracting `issue_key` (or the whole key-issuance primitive) into a
module neither `admin.py` nor `features/auth/service.py` needs to import
from the other side, but that's out of scope for this task.

## Fix pass (post-review)

Code review flagged an Important atomicity bug inherited from the brief's
Step 3 code, in `signup_trial`'s original ordering:

1. `session.add(user); session.flush()`
2. `ensure_trial_plan(session)`

`ensure_trial_plan`'s `except IntegrityError: session.rollback()` branch is
taken only when two first-ever trial signups race on an empty `plans`
table — but `session.rollback()` rolls back the **whole transaction**, not
just the plan insert. With the plan check happening after the user was
already flushed, that rollback would silently discard the just-created user
too, while `register_device(user=user, ...)` and
`redeem_key(user_id=user.id, ...)` downstream kept referencing the now-stale
`user` object — a real atomicity violation, just narrow (only reachable on
the very first concurrent trial signups before any plan row exists).

**Fix applied**: moved `ensure_trial_plan(session)` to immediately after
`now = now or utc_now()`, before `session.add(user)`, with an inline comment
explaining why the ordering matters:

```python
now = now or utc_now()
# Ensure the plan before creating the user, so a plan-race rollback can't
# discard the user: ensure_trial_plan's IntegrityError handler rolls back
# the whole transaction (harmless here, since nothing else is pending yet),
# whereas doing this after the user flush would roll the user back too and
# leave register_device/redeem_key operating on a detached object.
ensure_trial_plan(session)
user = models.User(
    email=normalize_email(email),
    password_hash=hash_password(password),
    status="active",
)
session.add(user)
try:
    session.flush()
except IntegrityError as error:
    session.rollback()
    raise AuthError("email_taken") from error
```

Now a plan-race rollback has nothing else pending to lose (the user hasn't
been created yet), and the later `email_taken` rollback still correctly
aborts the whole (failed) signup attempt since nothing depends on the user
after that point.

### Re-verification

```
$ python -m pytest tests/cloud/test_signup.py tests/cloud/test_licensing.py -v
tests/cloud/test_signup.py::test_signup_creates_active_user_trial_key_and_entitlement PASSED
tests/cloud/test_signup.py::test_signup_duplicate_email_rejected PASSED
tests/cloud/test_licensing.py::test_redeem_issues_a_verifiable_entitlement_and_consumes_one_use PASSED
tests/cloud/test_licensing.py::test_second_redeem_same_device_is_idempotent PASSED
tests/cloud/test_licensing.py::test_single_use_key_is_exhausted_on_a_second_device PASSED
tests/cloud/test_licensing.py::test_multi_use_key_covers_several_devices_then_exhausts PASSED
tests/cloud/test_licensing.py::test_invalid_key_is_rejected PASSED
tests/cloud/test_licensing.py::test_bad_key_states_are_rejected[suspended-False-key_suspended] PASSED
tests/cloud/test_licensing.py::test_bad_key_states_are_rejected[revoked-False-key_revoked] PASSED
tests/cloud/test_licensing.py::test_bad_key_states_are_rejected[active-True-key_expired] PASSED
tests/cloud/test_licensing.py::test_expiring_key_stamps_trial_end_claim PASSED
tests/cloud/test_licensing.py::test_non_expiring_key_has_no_trial_end PASSED
tests/cloud/test_licensing.py::test_refresh_reissues_a_fresh_entitlement_for_a_redeemed_device PASSED
tests/cloud/test_licensing.py::test_refresh_without_a_redemption_is_not_entitled PASSED
tests/cloud/test_licensing.py::test_refresh_stops_when_the_device_is_revoked PASSED
tests/cloud/test_licensing.py::test_refresh_stops_when_the_key_is_revoked PASSED
tests/cloud/test_licensing.py::test_refresh_stops_when_the_key_is_expired PASSED
============================= 17 passed in 1.76s ==============================
```

Also re-ran the full `tests/cloud` suite as a sanity check:
`93 passed, 3 skipped in 12.31s` (no regressions).

### Commit

`de49516` — `fix(cloud): ensure the trial plan before creating the user in
signup_trial` (local, on `feat/signup-trial`, new commit, not amended, not
pushed). Staged only `cloud/features/auth/service.py`.
