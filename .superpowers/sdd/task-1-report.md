# Task 1: Cloud — `trial_end` Entitlement Claim — Completion Report

## Summary
Implemented the `trial_end` entitlement claim via TDD. `_build_claims` now accepts
an optional `trial_end: datetime | None` and stamps `claims["trial_end"] =
int(trial_end.timestamp())` only when provided. `_issue_entitlement` passes
`ensure_aware_utc(key.expires_at)` as that value — the redeemed key's expiry is the
single source of truth. Because both `redeem_key` and `refresh_entitlement` call
`_issue_entitlement`, both inherit the claim automatically; no changes were needed
to either of those two functions themselves.

**Commit:** `40878b3` — `feat(cloud): stamp a trial_end claim from the key expiry`
**Branch:** `feat/signup-trial` (local commit only, not pushed, per instructions)

---

## Adapting the brief's tests to the real `_setup`

The brief's test skeleton assumed `_setup` returns `raw_key`/`user_id`/`device_a` and
that `RedeemResult` needs `now=`/`select(...)` gymnastics to mutate `expires_at`
after seeding. The actual `_setup(session_factory, *, max_uses=1, status="active",
expires_at=None)` in `tests/cloud/test_licensing.py`:

- returns `display` (not `raw_key`) for the plaintext key string,
- already accepts `expires_at` as a direct keyword argument (no need to fetch the
  row via `select(models.ActivationKey)` and mutate it in a second session — that's
  exactly how the existing `test_bad_key_states_are_rejected` parametrized test sets
  up an expired key),
- has no `raw_key`/`ctx["raw_key"]` key in its returned dict.

The brief also claimed `datetime`, `timezone`, and `select` were "already imported"
in the test module — they were not (only `timedelta` was imported from `datetime`;
`select` isn't imported at all). Rather than adding those imports to replicate the
brief's literal approach, I mirrored the file's own idiom instead: build
`expires_at` with `utc_now() + timedelta(days=30)` (exactly how
`test_bad_key_states_are_rejected` builds its expired-key case with
`utc_now() - timedelta(days=1)`), pass it straight into `_setup(...)`, and redeem via
the existing `_redeem(session_factory, ctx, device_id)` helper (which already wraps
`redeem_key` + commit, used by every other redeem test in the file). This kept the
new tests indistinguishable in style from their neighbors and required zero new
imports.

Final tests (inserted directly after `test_bad_key_states_are_rejected`, before the
`_refresh` helper):

```python
def test_expiring_key_stamps_trial_end_claim(session_factory):
    expires_at = utc_now() + timedelta(days=30)
    ctx = _setup(session_factory, expires_at=expires_at)
    result = _redeem(session_factory, ctx, ctx["device_a"])
    assert result.claims["trial_end"] == int(expires_at.timestamp())


def test_non_expiring_key_has_no_trial_end(session_factory):
    ctx = _setup(session_factory)  # default expires_at=None (non-trial key)
    result = _redeem(session_factory, ctx, ctx["device_a"])
    assert "trial_end" not in result.claims
```

`RedeemResult.claims` is already a plain `dict` returned by `redeem_key` (see
`cloud/licensing.py`), so asserting on `result.claims["trial_end"]` directly (as the
brief specified) needed no detour through `verify_entitlement`/`PUBLIC_KEY`.

---

## TDD Evidence

### RED (failing for the right reason)
Command:
```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pytest tests/cloud/test_licensing.py -k trial_end -v
```
Output (before implementation):
```
tests/cloud/test_licensing.py::test_expiring_key_stamps_trial_end_claim FAILED [ 50%]
tests/cloud/test_licensing.py::test_non_expiring_key_has_no_trial_end PASSED [100%]

________________ test_expiring_key_stamps_trial_end_claim ________________
>       assert result.claims["trial_end"] == int(expires_at.timestamp())
E       KeyError: 'trial_end'

======================= 1 failed, 1 passed in 0.89s =======================
```
This is the expected RED: the positive-case test fails with `KeyError: 'trial_end'`
because the claim doesn't exist yet. The negative-case test (`not in result.claims`)
is trivially true pre-implementation too — that's expected and correct; it's there
to lock in the invariant going forward, not to prove RED on its own.

### GREEN (after implementing `_build_claims` / `_issue_entitlement`)
Command:
```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pytest tests/cloud/test_licensing.py -v
```
Output:
```
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

======================== 15 passed in 1.29s ========================
```

### Broader regression check
Also ran the full `tests/cloud/` directory (91 passed, 3 skipped — the skipped ones
are Postgres-only concurrency tests that don't run against SQLite):
```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pytest tests/cloud/ -v
...
================== 91 passed, 3 skipped, 1 warning in 12.08s ==================
```

---

## Files Changed

```
cloud/licensing.py             (+7/-1)
tests/cloud/test_licensing.py  (+13)
```

Diff of `cloud/licensing.py`:
```python
 def _build_claims(
     *,
     entitlement_id: str,
     key_id: str,
     user_id: str,
     device_id: str,
     plan: models.Plan,
     now: datetime,
     expires_at: datetime,
     grace_deadline: datetime,
+    trial_end: datetime | None = None,
 ) -> dict:
-    return {
+    claims = {
         "jti": entitlement_id,
         "sub": user_id,
         "device_id": device_id,
         "key_id": key_id,
         "plan": plan.id,
         "features": _plan_features(plan),
         "profile_limit": plan.max_profiles,
         "session_limit": plan.max_sessions,
         "device_limit": plan.max_devices,
         "iat": int(now.timestamp()),
         "exp": int(expires_at.timestamp()),
         "offline_grace_deadline": int(grace_deadline.timestamp()),
         "entitlement_version": ENTITLEMENT_VERSION,
     }
+    if trial_end is not None:
+        claims["trial_end"] = int(trial_end.timestamp())
+    return claims
```
And in `_issue_entitlement`, the call site:
```python
     claims = _build_claims(
         entitlement_id=entitlement_id,
         key_id=key.id,
         user_id=user_id,
         device_id=device_id,
         plan=plan,
         now=now,
         expires_at=expires_at,
         grace_deadline=grace_deadline,
+        trial_end=ensure_aware_utc(key.expires_at),
     )
```

`ensure_aware_utc` was already imported in `cloud/licensing.py` (line 32, used by
`redeem_key`/`refresh_entitlement` for their own expiry checks), so no new import
was required.

Staged and committed via:
```bash
git add cloud/licensing.py tests/cloud/test_licensing.py
git commit -m "feat(cloud): stamp a trial_end claim from the key expiry ..."
```
Confirmed only these two files were staged (`git status` showed several unrelated
pre-existing working-tree modifications from other in-flight tasks —
`.impeccable/hook.cache.json`, other `task-*-brief.md`/`task-*-report.md` files, a
deleted `Velas Component Colors.dc.html` — none of which were touched or staged).

---

## Self-Review

- **Non-expiring key emits no `trial_end`**: confirmed by
  `test_non_expiring_key_has_no_trial_end`, which redeems a key seeded with the
  default `expires_at=None` and asserts `"trial_end" not in result.claims`. Traced
  through the code: `ensure_aware_utc(None)` returns `None` (per its own docstring/
  implementation in `cloud/db.py`), so `_build_claims`'s `if trial_end is not None`
  guard never adds the key, matching the brief's requirement exactly.
- **Expiring key stamps the correct value**: `test_expiring_key_stamps_trial_end_claim`
  asserts the claim equals `int(expires_at.timestamp())` for a key seeded with a
  30-day-out expiry. SQLite (used in tests) drops tzinfo on read-back for
  `DateTime(timezone=True)` columns, which is exactly why `_issue_entitlement` routes
  the key's expiry through `ensure_aware_utc` before handing it to `_build_claims` —
  this was already the established pattern in `redeem_key`/`refresh_entitlement` for
  the same reason, so `trial_end` follows the same discipline as `exp`.
  `.timestamp()` is invariant under the aware/naive round-trip here since both
  represent the same UTC instant, so the equality check is not a coincidence of
  SQLite's clock precision.
- **`redeem_key` and `refresh_entitlement` both inherit it**: verified structurally
  — neither function was touched; both call `_issue_entitlement`, which is the only
  caller of `_build_claims`, and it now always threads `key.expires_at` through. The
  brief only required a redeem-path test since the two paths share this single
  choke point; I did not add a duplicate refresh-path test for the same claim logic
  (would be testing the same code path twice), but did rely on the pre-existing
  `test_refresh_reissues_a_fresh_entitlement_for_a_redeemed_device` passing
  unmodified as a sanity check that `refresh_entitlement` still works with the new
  parameter's default (`trial_end=None`) not breaking anything.
- **Existing tests unaffected**: all 13 pre-existing tests in
  `tests/cloud/test_licensing.py` pass unmodified, and the full `tests/cloud/`
  suite (91 passed / 3 skipped) shows no regressions elsewhere (e.g.
  `test_entitlements.py`'s sign/verify round-trip tests, which exercise the same
  claims dict shape downstream, are unaffected since `trial_end` is purely additive
  and optional).

## Concerns

None blocking. Two minor adaptation notes, both already covered above:
1. The brief's assumption about `_setup`'s return keys (`raw_key`/`user_id`/
   `device_a`) and about `datetime`/`timezone`/`select` being pre-imported in the
   test module was incorrect for this codebase's actual state — I adapted per the
   task's own explicit instruction to do so, following the file's existing
   conventions rather than the brief's literal transcription.
2. Git line-ending warnings ("LF will be replaced by CRLF") appeared on `git add`/
   `commit` for both files — this is a pre-existing repo/OS artifact, not something
   introduced by this change, and required no action.

---

## Verification Checklist
- [x] TDD flow executed: RED (`KeyError: 'trial_end'`) -> GREEN
- [x] New tests (2) + all existing licensing tests (13) pass — 15/15
- [x] Full `tests/cloud/` suite passes with no regressions (91 passed, 3 skipped/Postgres-only)
- [x] Only `cloud/licensing.py` and `tests/cloud/test_licensing.py` staged and committed
- [x] Commit body ends with the required `Co-Authored-By` trailer
- [x] Non-expiring key verified to emit no `trial_end` claim
- [x] Not pushed (local commit only, per instructions)

---

**Status:** DONE
**Date:** 2026-07-24
**Branch:** `feat/signup-trial`
**Commit SHA:** `40878b3`
