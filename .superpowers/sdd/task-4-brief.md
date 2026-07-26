### Task 4: Desktop — license state-machine `trial_end` hard-cap

**Files:**
- Modify: `manager_backend/features/license/service.py`, `manager_backend/features/license/schemas.py`
- Test: `tests/manager/test_license.py`

**Interfaces:**
- Produces: `LicenseStatus` gains `trial_end: int | None = None`; `evaluate_license` forces `state="expired"` when `now > trial_end` (a claim), regardless of `exp`/grace; `LicenseStatusRead` surfaces `trial_end`.

- [ ] **Step 1: Write the failing test** (append to `tests/manager/test_license.py`)

The existing `_entitlement` helper builds claims — extend a copy for trial_end, or add the kwarg. Add these tests (they construct claims directly, so they don't need the cloud endpoint):

```python
def test_trial_end_in_past_forces_expired_even_within_grace(tmp_path):
    priv, pub = _keypair()
    s = _settings(tmp_path, pubkey=pub)
    now = 1_000_000
    # exp + grace are both in the FUTURE (would normally be "active"), but the trial
    # ended → hard expired.
    claims = {
        "exp": now + 1000,
        "offline_grace_deadline": now + 10_000,
        "plan": "trial",
        "features": [],
        "trial_end": now - 1,
    }
    service.save_entitlement(s, sign_entitlement(claims, priv))
    status = service.evaluate_license(s, now=now)
    assert status.state == "expired" and not status.allowed
    assert status.trial_end == now - 1


def test_trial_end_in_future_is_active(tmp_path):
    priv, pub = _keypair()
    s = _settings(tmp_path, pubkey=pub)
    now = 1_000_000
    claims = {
        "exp": now + 1000,
        "offline_grace_deadline": now + 10_000,
        "plan": "trial",
        "features": [],
        "trial_end": now + 100_000,
    }
    service.save_entitlement(s, sign_entitlement(claims, priv))
    status = service.evaluate_license(s, now=now)
    assert status.state == "active" and status.allowed
```

`_keypair`, `_settings`, `sign_entitlement`, `service` are already imported/defined in this test module.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/manager/test_license.py -k trial_end -v`
Expected: FAIL — `AttributeError: 'LicenseStatus' object has no attribute 'trial_end'` (and the past-trial case would be `active`, not `expired`).

- [ ] **Step 3a: Implement** — in `manager_backend/features/license/service.py`.

Add the field to `LicenseStatus`:
```python
@dataclass
class LicenseStatus:
    state: str
    allowed: bool
    plan: str | None = None
    features: list[str] = field(default_factory=list)
    expires_at: int | None = None
    grace_deadline: int | None = None
    trial_end: int | None = None  # epoch seconds; hard trial cutoff (trial keys only)
    detail: str | None = None
```

In `evaluate_license`, after the `exp`/`grace` `isinstance` guard and before returning, replace the state branch:
```python
    features = claims.get("features") or []
    plan = claims.get("plan")
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
    return LicenseStatus(
        state=state,
        allowed=state in _ALLOWED_STATES,
        plan=plan,
        features=list(features),
        expires_at=exp,
        grace_deadline=grace,
        trial_end=trial_end,
    )
```

- [ ] **Step 3b: Surface it** — in `manager_backend/features/license/schemas.py`, add `trial_end: int | None = None` to `LicenseStatusRead`'s fields and to its `.of()` classmethod (`trial_end=status.trial_end`).

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/manager/test_license.py -v`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add manager_backend/features/license/service.py manager_backend/features/license/schemas.py tests/manager/test_license.py
git commit -m "feat(license): trial_end hard-cap in the state machine"
```

---

