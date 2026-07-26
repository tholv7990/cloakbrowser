### Task 1: Cloud — `trial_end` entitlement claim

**Files:**
- Modify: `cloud/licensing.py` (`_build_claims`, `_issue_entitlement`)
- Test: `tests/cloud/test_licensing.py`

**Interfaces:**
- Produces: entitlement claims now include `"trial_end": int(key.expires_at.timestamp())` when the redeemed/refreshed key has an `expires_at` (absent otherwise). Both `redeem_key` and `refresh_entitlement` inherit this (they call `_issue_entitlement`).

- [ ] **Step 1: Write the failing test** (append to `tests/cloud/test_licensing.py`)

```python
def test_expiring_key_stamps_trial_end_claim(session_factory):
    ctx = _setup(session_factory)  # existing helper: seeds plan + a redeemable key
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    thirty = now + timedelta(days=30)
    with session_factory() as session:
        # Give the seeded key a 30-day expiry.
        key = session.execute(select(models.ActivationKey)).scalar_one()
        key.expires_at = thirty
        session.flush()
        result = redeem_key(
            session,
            raw_key=ctx["raw_key"],
            user_id=ctx["user_id"],
            device_id=ctx["device_a"],
            pepper=PEPPER,
            private_key=PRIVATE_KEY,
            now=now,
        )
    assert result.claims["trial_end"] == int(thirty.timestamp())


def test_non_expiring_key_has_no_trial_end(session_factory):
    ctx = _setup(session_factory)  # seeded key has expires_at = None
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with session_factory() as session:
        result = redeem_key(
            session,
            raw_key=ctx["raw_key"],
            user_id=ctx["user_id"],
            device_id=ctx["device_a"],
            pepper=PEPPER,
            private_key=PRIVATE_KEY,
            now=now,
        )
    assert "trial_end" not in result.claims
```

If `_setup` does not expose `raw_key`/`user_id`/`device_a`, read the existing `_setup` in this file and reuse whatever keys it returns (the file already calls `redeem_key` with these exact kwargs — mirror its existing successful-redeem test). `datetime`, `timezone`, `timedelta`, `select`, `models`, `redeem_key`, `PEPPER`, `PRIVATE_KEY` are already imported/defined in this test module.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/cloud/test_licensing.py -k trial_end -v`
Expected: FAIL — `KeyError: 'trial_end'` (claim not emitted yet).

- [ ] **Step 3: Implement** — in `cloud/licensing.py`, thread `trial_end` through the two claim builders.

Change `_build_claims` (add the parameter + conditional claim):
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
    trial_end: datetime | None = None,
) -> dict:
    claims = {
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
    if trial_end is not None:
        claims["trial_end"] = int(trial_end.timestamp())
    return claims
```

In `_issue_entitlement`, pass the key's expiry (single source of truth) to `_build_claims`:
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
        trial_end=ensure_aware_utc(key.expires_at),
    )
```

`ensure_aware_utc` is already imported in `cloud/licensing.py` (used by `redeem_key`). It returns `None` for a `None` input, so non-expiring keys emit no `trial_end`.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/cloud/test_licensing.py -v`
Expected: PASS (new tests + all existing licensing tests).

- [ ] **Step 5: Commit**

```bash
git add cloud/licensing.py tests/cloud/test_licensing.py
git commit -m "feat(cloud): stamp a trial_end claim from the key expiry"
```

---

