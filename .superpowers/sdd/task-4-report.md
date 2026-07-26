# Task 4 Report — Desktop license state-machine `trial_end` hard-cap

## Status: DONE

## Summary

Implemented per the brief with no deviations. The brief's shape matched the
actual code exactly (`LicenseStatus` dataclass, `evaluate_license` return
statement, `LicenseStatusRead` + `.of()` in `schemas.py`), so no adaptation
was needed.

## TDD — RED

Appended two tests to `tests/manager/test_license.py` (verbatim from the
brief, right after `test_active_grace_expired_transitions` / before
`test_wrong_signing_key_is_invalid`):

- `test_trial_end_in_past_forces_expired_even_within_grace`
- `test_trial_end_in_future_is_active`

Command:
```
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pytest tests/manager/test_license.py -k trial_end -v
```

Result (before implementation): 1 failed, 1 passed.

- `test_trial_end_in_past_forces_expired_even_within_grace` **FAILED**:
  `AssertionError: assert ('active' == 'expired' ...)` — the past-trial case
  evaluated to `active` instead of `expired`, exactly as the brief predicted
  (no `AttributeError` since the test never reads `status.trial_end` before
  the state assertion fails first).
- `test_trial_end_in_future_is_active` **PASSED** trivially — this case
  would already be `active` from the pre-existing `exp`/`grace` logic alone,
  since it never inspects `status.trial_end`. This is expected per the brief;
  it isn't a discriminating regression test on its own but documents the
  non-cap case and exercises the new `trial_end` claim parsing path.

This confirms RED for the behavior that matters (the hard-cap).

## Implementation

1. `manager_backend/features/license/service.py`
   - Added `trial_end: int | None = None` field to `LicenseStatus` (after
     `grace_deadline`, before `detail`).
   - In `evaluate_license`, after computing `features`/`plan`, added:
     ```python
     trial_end = claims.get("trial_end")
     trial_end = trial_end if isinstance(trial_end, int) else None
     if trial_end is not None and now > trial_end:
         state = "expired"  # trial hard-cap wins over exp/grace
     elif now <= exp:
         state = "active"
     elif now <= grace:
         state = "grace"
     else:
         state = "expired"
     ```
     and passed `trial_end=trial_end` into the returned `LicenseStatus`.

2. `manager_backend/features/license/schemas.py`
   - Added `trial_end: int | None = None` to `LicenseStatusRead`.
   - Added `trial_end=status.trial_end` to `.of()`.

## TDD — GREEN

Command:
```
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pytest tests/manager/test_license.py -v
```
Result: **12 passed** (10 pre-existing + 2 new), 1 unrelated deprecation warning
(`httpx`/starlette TestClient), 1.28s.

Regression check:
```
& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pytest tests/manager/test_account.py -v
```
Result: **5 passed**, no regressions (account flows evaluate license state via
the same `evaluate_license`, unaffected since none of those entitlements carry
`trial_end`).

## Self-review

- **Non-trial entitlements unaffected**: when `claims.get("trial_end")` is
  absent, it's `None`; the `isinstance(trial_end, int)` guard makes
  `trial_end = None`, so the new `if trial_end is not None and ...` branch is
  skipped entirely and the original `active`/`grace`/`expired` logic runs
  unchanged. Confirmed by all 10 pre-existing tests staying green, including
  `test_active_grace_expired_transitions` and the API-level
  `test_api_status_install_deactivate`.
- **Trial hard-cap wins over grace**: the new branch is checked first (before
  the `now <= exp` / `now <= grace` elifs), so a `trial_end` in the past forces
  `expired` even when `exp` and `grace` are both still in the future. Verified
  directly by `test_trial_end_in_past_forces_expired_even_within_grace`.
- **Type safety**: `trial_end` is guarded with `isinstance(..., int)` exactly
  like the existing `exp`/`grace` guards, so a malformed/non-int claim is
  treated as "no cap" rather than raising or silently misbehaving (consistent
  with the fail-closed-on-malformed-*required*-claims but fail-open-on-missing
  *optional*-claims pattern already used for `features`/`plan`).
- **`LicenseStatusRead` mirrors `LicenseStatus`**: field-for-field parity
  confirmed by reading both files before editing; `trial_end` added to both
  the field list and `.of()`.

No concerns. No adaptations were needed — the brief's code matched the repo
exactly.

## Files changed

- `manager_backend/features/license/service.py`
- `manager_backend/features/license/schemas.py`
- `tests/manager/test_license.py`

## Commit

Branch: `feat/signup-trial` (not pushed)
```
734e100 feat(license): trial_end hard-cap in the state machine
```
3 files changed, 44 insertions(+), 1 deletion(-).

## Note on this report file

This exact path (`.superpowers/sdd/task-4-report.md`) previously held an
unrelated report from a different parallel task run ("Synchronize
window-tiling" — schemas/routes/app-wiring for monitors + windows/arrange
endpoints, commit `1884b0a` on `feat/synchronize-window-tiling`). That
content has been overwritten with this report per the explicit target path
given in this task's instructions. If that window-tiling report is still
needed, retrieve it from git history (it was committed under a different
branch/commit than this task's work) before this overwrite is committed
anywhere it could be lost for good.
