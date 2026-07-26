### Task 2: Cloud — `signup_trial` service

**Files:**
- Modify: `cloud/features/auth/service.py`
- Test: `tests/cloud/test_signup.py` (create)

**Interfaces:**
- Consumes: `_issue_entitlement`/`redeem_key` trial_end behavior (Task 1); `issue_key` (`cloud/admin.py`), `redeem_key` (`cloud/licensing.py`), `register_device` + the device-challenge format (`cloud/features/devices/service.py`), `create_session` + `normalize_email` + `hash_password` (this module / `cloud/keys.py` / `cloud/passwords.py`).
- Produces:
  - `TRIAL_PLAN_ID = "trial"`, `TRIAL_DAYS = 30`
  - `ensure_trial_plan(session) -> models.Plan`
  - `@dataclass SignupResult` with `tokens: IssuedTokens`, `entitlement_token: str`
  - `signup_trial(session, *, email: str, password: str, device_public_key: str, device_signature: str, device_name: str = "Plasma Desktop", settings: CloudSettings, now: datetime | None = None, trial_days: int = TRIAL_DAYS) -> SignupResult` — raises `AuthError("email_taken")` on a duplicate email; propagates `DeviceError`/`RedeemError`.

- [ ] **Step 1: Write the failing test** (`tests/cloud/test_signup.py`)

```python
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from cloud import models
from cloud.config import generate_test_settings
from cloud.db import Base, create_engine_for, create_session_factory
from cloud.entitlements import public_key_to_b64, verify_entitlement
from cloud.features.auth.service import AuthError, signup_trial

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine_for(f"sqlite:///{(tmp_path / 'cloud.db').as_posix()}")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _device():
    private = Ed25519PrivateKey.generate()
    public_b64 = public_key_to_b64(private.public_key())
    challenge = f"plasma-device:{public_b64}"
    signature_b64 = base64.b64encode(private.sign(challenge.encode())).decode("ascii")
    return public_b64, signature_b64


def test_signup_creates_active_user_trial_key_and_entitlement(session_factory):
    settings = generate_test_settings()
    pub, sig = _device()
    with session_factory() as session:
        result = signup_trial(
            session,
            email="New@Example.com",
            password="correct horse battery staple",
            device_public_key=pub,
            device_signature=sig,
            settings=settings,
            now=NOW,
        )
        session.commit()
        user = session.execute(
            select(models.User).where(models.User.email == "new@example.com")
        ).scalar_one()
        assert user.status == "active"

    claims = verify_entitlement(result.entitlement_token, settings.signing_public_key)
    assert claims["plan"] == "trial"
    assert claims["trial_end"] == int((NOW + timedelta(days=30)).timestamp())
    assert result.tokens.refresh_token  # a session was minted


def test_signup_duplicate_email_rejected(session_factory):
    settings = generate_test_settings()
    pub, sig = _device()
    with session_factory() as session:
        signup_trial(
            session, email="dup@example.com", password="correct horse battery staple",
            device_public_key=pub, device_signature=sig, settings=settings, now=NOW,
        )
        session.commit()
    pub2, sig2 = _device()
    with session_factory() as session:
        with pytest.raises(AuthError) as error:
            signup_trial(
                session, email="dup@example.com", password="another good password here",
                device_public_key=pub2, device_signature=sig2, settings=settings, now=NOW,
            )
    assert error.value.code == "email_taken"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/cloud/test_signup.py -v`
Expected: FAIL — `ImportError: cannot import name 'signup_trial'`.

- [ ] **Step 3: Implement** — add to `cloud/features/auth/service.py`.

At the top, ensure these imports exist (add any missing): `from datetime import timedelta`, `from ...admin import issue_key`, `from ...licensing import redeem_key`, `from ..devices.service import register_device`, and `from ...keys import normalize_email` (already used by `authenticate`/`register_user`). `IntegrityError`, `models`, `hash_password`, `utc_now`, `create_session`, `IssuedTokens`, `CloudSettings` are already imported/defined in this module.

Add:
```python
TRIAL_PLAN_ID = "trial"
TRIAL_DAYS = 30


def ensure_trial_plan(session) -> models.Plan:
    """Get-or-create the trial plan (idempotent; safe on a fresh DB and across
    concurrent signups). Reused instead of a seed migration so signup is
    self-contained."""
    plan = session.get(models.Plan, TRIAL_PLAN_ID)
    if plan is not None:
        return plan
    plan = models.Plan(
        id=TRIAL_PLAN_ID, name="Trial", max_devices=1, max_profiles=50,
        max_sessions=5, features={},
    )
    session.add(plan)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()  # a concurrent signup created it first
        plan = session.get(models.Plan, TRIAL_PLAN_ID)
    return plan


@dataclass
class SignupResult:
    tokens: IssuedTokens
    entitlement_token: str


def signup_trial(
    session,
    *,
    email: str,
    password: str,
    device_public_key: str,
    device_signature: str,
    device_name: str = "Plasma Desktop",
    settings: CloudSettings,
    now: datetime | None = None,
    trial_days: int = TRIAL_DAYS,
) -> SignupResult:
    """Register an ACTIVE account (no email verification), grant a `trial_days`
    trial license, attach the device, and redeem the key — all in one transaction.
    Returns the session tokens + the signed trial entitlement."""
    now = now or utc_now()
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

    ensure_trial_plan(session)
    display, _key = issue_key(
        session,
        plan_id=TRIAL_PLAN_ID,
        pepper=settings.activation_pepper,
        max_uses=1,
        expires_at=now + timedelta(days=trial_days),
        created_by="system",
    )
    # Canonical device possession challenge — mirrors auth/routes.device_challenge.
    device = register_device(
        session,
        user=user,
        public_key_b64=device_public_key,
        challenge=f"plasma-device:{device_public_key}",
        signature_b64=device_signature,
        name=device_name,
    )
    issued = create_session(session, user=user, device=device, settings=settings, now=now)
    redeemed = redeem_key(
        session,
        raw_key=display,
        user_id=user.id,
        device_id=device.id,
        pepper=settings.activation_pepper,
        private_key=settings.signing_private_key,
        now=now,
        ttl=settings.entitlement_ttl,
        grace=settings.offline_grace,
    )
    return SignupResult(tokens=issued, entitlement_token=redeemed.token)
```

If `register_device`'s keyword names differ from `public_key_b64`/`challenge`/`signature_b64`/`name`, read `cloud/features/devices/service.py::register_device` and match its exact signature.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/cloud/test_signup.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add cloud/features/auth/service.py tests/cloud/test_signup.py
git commit -m "feat(cloud): signup_trial service (active user + 30-day trial + redeem)"
```

---

