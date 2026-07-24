# Sign-up + 30-day Trial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An in-app Sign-up flow (email + password + confirm) that creates an active cloud account, grants a 30-day trial license, activates it on the device, and unlocks the app — the trial hard-expires at 30 days.

**Architecture:** A new atomic cloud endpoint `POST /auth/signup` (active user + trial key `expires_at=now+30d` + device attach + session + redeem → session & entitlement); a `trial_end` entitlement claim (= the key's `expires_at`) enforced by the desktop license state machine as a hard cap; a desktop `AccountService.register` bridge; and a `SignUpPanel` in the desktop License screen.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + argon2 + Ed25519 (cloud & manager_backend), React + TanStack Query + react-hook-form + Vitest (frontend).

## Global Constraints

- **Three-ports rule does NOT apply** — this is `cloud/` + `manager_backend/` + `manager/frontend/`, not the `cloakbrowser` wrapper. Do not touch `cloakbrowser/`, `js/`, `dotnet/`.
- **Never log secrets** — password, activation key, access/refresh tokens, entitlement token. Fixed, safe error codes only.
- **Password min length 12** on both the cloud `SignupRequest` and the desktop `RegisterRequest` (matches the existing `RegisterRequest` policy and the `auth.passwordHint` copy).
- **Trial = 30 days.** `trial_end` claim = the trial key's `expires_at` (single source of truth); `now > trial_end` → license `expired`.
- **Trial accounts are created `status="active"`** (skip email verification). This applies to the signup path only; `/auth/register` (verification flow) is unchanged.
- **`confirm_password` is client-side only** — never sent to any backend.
- Entitlement Ed25519 sign/verify chain is unchanged (only a new claim is added).
- **Commits:** local per-task commits on a NEW feature branch `feat/signup-trial` (create it before Task 1). Do NOT push; merge to main is gated on the user's explicit approval. End every commit body with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- **Test commands:** cloud `python -m pytest tests/cloud/<file> -v`; desktop `python -m pytest tests/manager/<file> -v` (system Python 3.13: `& "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" -m pytest ...`); frontend `npm --prefix manager/frontend run <script>`.

## File Structure

**Cloud (modify):**
- `cloud/licensing.py` — `_build_claims`/`_issue_entitlement` gain a `trial_end` claim from the key's `expires_at`.
- `cloud/features/auth/service.py` — new `ensure_trial_plan`, `signup_trial`, `SignupResult`, `TRIAL_PLAN_ID`, `TRIAL_DAYS`.
- `cloud/schemas.py` — `SignupRequest`, `SignupResponse`.
- `cloud/features/auth/routes.py` — `POST /auth/signup`.
- Tests: `tests/cloud/test_licensing.py` (+trial_end), `tests/cloud/test_signup.py` (new).

**Desktop backend (modify):**
- `manager_backend/features/license/service.py` — `trial_end` hard-cap + `LicenseStatus.trial_end`.
- `manager_backend/features/license/schemas.py` — `LicenseStatusRead.trial_end`.
- `manager_backend/features/account/cloud_client.py` — `register`.
- `manager_backend/features/account/service.py` — `register`, `email_taken` error map.
- `manager_backend/features/account/schemas.py` — `RegisterRequest`.
- `manager_backend/features/account/routes.py` — `POST /account/register`.
- Tests: `tests/manager/test_license.py` (+trial_end), `tests/manager/test_account.py` (+register).

**Frontend (modify + create):**
- `manager/frontend/src/types/api.ts` — `LicenseStatus.trial_end?`.
- `manager/frontend/src/api/adapter.ts`, `api/real.ts`, `mocks/mockApi.ts` — `accountRegister`.
- `manager/frontend/src/features/account/api.ts` — `useAccountRegister`.
- `manager/frontend/src/features/account/LicenseScreen.tsx` — `SignUpPanel` + Sign in⇄Sign up toggle.
- `manager/frontend/src/features/account/SignUpPanel.test.tsx` — new.
- `manager/frontend/src/i18n/en.ts`, `i18n/vi.ts` — new `account.*` keys.

---

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

### Task 3: Cloud — `POST /auth/signup` route + schemas

**Files:**
- Modify: `cloud/schemas.py`, `cloud/features/auth/routes.py`
- Test: `tests/cloud/test_signup.py`

**Interfaces:**
- Consumes: `signup_trial`/`SignupResult` (Task 2).
- Produces: `POST /auth/signup` → `SignupResponse { access_token, refresh_token, token_type, expires_in, entitlement_token }`.

- [ ] **Step 1: Write the failing test** (append to `tests/cloud/test_signup.py`)

```python
from fastapi.testclient import TestClient

from cloud.app import create_app
from cloud.email import RecordingEmailSender


def _app(session_factory):
    settings = generate_test_settings()
    app = create_app(settings, session_factory=session_factory, email_sender=RecordingEmailSender())
    return TestClient(app), settings


def test_signup_endpoint_returns_session_and_trial_entitlement(session_factory):
    client, settings = _app(session_factory)
    pub, sig = _device()
    resp = client.post(
        "/auth/signup",
        json={
            "email": "web@example.com",
            "password": "correct horse battery staple",
            "device_public_key": pub,
            "device_signature": sig,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    claims = verify_entitlement(body["entitlement_token"], settings.signing_public_key)
    assert claims["plan"] == "trial" and "trial_end" in claims


def test_signup_endpoint_rejects_short_password(session_factory):
    client, _ = _app(session_factory)
    pub, sig = _device()
    resp = client.post(
        "/auth/signup",
        json={"email": "x@example.com", "password": "short", "device_public_key": pub, "device_signature": sig},
    )
    assert resp.status_code == 422


def test_signup_endpoint_duplicate_email(session_factory):
    client, _ = _app(session_factory)
    pub, sig = _device()
    payload = {"email": "dupe@example.com", "password": "correct horse battery staple",
               "device_public_key": pub, "device_signature": sig}
    assert client.post("/auth/signup", json=payload).status_code == 200
    pub2, sig2 = _device()
    payload2 = {**payload, "device_public_key": pub2, "device_signature": sig2}
    resp = client.post("/auth/signup", json=payload2)
    assert resp.status_code >= 400
    assert resp.json()["error"] == "email_taken"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/cloud/test_signup.py -k endpoint -v`
Expected: FAIL — 404 (route not defined).

- [ ] **Step 3a: Add schemas** — append to `cloud/schemas.py`:

```python
class SignupRequest(StrictModel):
    """Register an ACTIVE trial account + attach the device in one call. The device
    proves possession by signing the canonical challenge for its public key."""

    email: EmailStr
    password: str = Field(min_length=12, max_length=1024)
    device_public_key: str = Field(min_length=1, max_length=128)
    device_signature: str = Field(min_length=1, max_length=128)
    device_name: str = Field(default="Plasma Desktop", max_length=120)


class SignupResponse(StrictModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    entitlement_token: str
```

- [ ] **Step 3b: Add the route** — in `cloud/features/auth/routes.py`, extend the schema import to include `SignupRequest, SignupResponse`, add `from ...licensing import RedeemError`, and add the handler (mirrors `token`):

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

`devices` and `CloudError` are already imported in `routes.py` (used by `token`). If `RedeemError`'s codes (e.g. `invalid_key`) lack a `STATUS` mapping in `cloud/errors.py`, they are already mapped because `/activation/redeem` uses them — no change needed. `email_taken` is likewise already mapped (used by `/auth/register`).

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/cloud/test_signup.py -v`
Expected: PASS (all signup tests). Then `python -m pytest tests/cloud -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add cloud/schemas.py cloud/features/auth/routes.py tests/cloud/test_signup.py
git commit -m "feat(cloud): POST /auth/signup endpoint"
```

---

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

### Task 5: Desktop — register bridge (client + service + schema + route)

**Files:**
- Modify: `manager_backend/features/account/cloud_client.py`, `service.py`, `schemas.py`, `routes.py`
- Test: `tests/manager/test_account.py`

**Interfaces:**
- Consumes: cloud `POST /auth/signup` (Task 3); `install_entitlement` + `LicenseStatus` (license service).
- Produces:
  - `CloudClient.register(*, email, password, device) -> dict` (`{access_token, refresh_token, expires_in, entitlement_token}`)
  - `AccountService.register(*, email, password) -> LicenseStatus`
  - `RegisterRequest { email, password }` (password `min_length=12`)
  - `POST /api/v1/account/register` → `LicenseStatusRead`

- [ ] **Step 1: Write the failing test** (append to `tests/manager/test_account.py`)

Uses the existing `cloud` + `account` fixtures (a real in-process cloud app + a fake-client-backed `AccountService`):

```python
def test_register_creates_trial_and_unlocks(cloud, account):
    svc, settings = account
    status = svc.register(email="fresh@example.com", password="correct horse battery staple")
    assert status.state == "active" and status.allowed
    assert status.trial_end is not None
    assert svc.status().signed_in is True
    assert license_service.evaluate_license(settings).state == "active"


def test_register_duplicate_email_is_safe_error(cloud, account):
    svc, _ = account
    svc.register(email="taken@example.com", password="correct horse battery staple")
    with pytest.raises(ManagerError) as err:
        svc.register(email="taken@example.com", password="correct horse battery staple")
    assert err.value.code == "cloud_email_taken"
```

`license_service`, `ManagerError`, `pytest` are already imported in this module.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/manager/test_account.py -k register -v`
Expected: FAIL — `AttributeError: 'AccountService' object has no attribute 'register'`.

- [ ] **Step 3a: `CloudClient.register`** — add to `manager_backend/features/account/cloud_client.py` (after `login`):
```python
    def register(self, *, email: str, password: str, device: DeviceIdentity) -> dict:
        """Create a trial account + attach this device -> {access_token,
        refresh_token, expires_in, entitlement_token}."""
        return self._post(
            "/auth/signup",
            {
                "email": email,
                "password": password,
                "device_public_key": device.public_key_b64,
                "device_signature": device.signature_b64(),
                "device_name": "Plasma Desktop",
            },
        )
```

- [ ] **Step 3b: `AccountService.register`** — add to `manager_backend/features/account/service.py` (after `login`), and add the `email_taken` mapping to `_CLOUD_ERRORS`:
```python
    def register(self, *, email: str, password: str) -> LicenseStatus:
        client = self._client()
        device = get_or_create_device(self._secrets)
        try:
            result = client.register(email=email, password=password, device=device)
        except CloudClientError as error:
            raise _manager_error(error) from error
        self._secrets.put(REFRESH_REF, result["refresh_token"])
        self._save_state({"email": email})
        return license_service.install_entitlement(self._settings, result["entitlement_token"])
```
Add to the `_CLOUD_ERRORS` dict:
```python
    "email_taken": ("An account with this email already exists.", 409),
```

- [ ] **Step 3c: `RegisterRequest`** — add to `manager_backend/features/account/schemas.py`:
```python
class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=12, max_length=1024)
```

- [ ] **Step 3d: route** — in `manager_backend/features/account/routes.py`, add `RegisterRequest` to the `.schemas` import and add:
```python
@router.post("/register", response_model=LicenseStatusRead, operation_id="account_register")
def register(request: Request, payload: RegisterRequest) -> LicenseStatusRead:
    return LicenseStatusRead.of(
        _service(request).register(email=str(payload.email), password=payload.password)
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/manager/test_account.py -v`
Expected: PASS. Then `python -m pytest tests/manager -q` → all pass (no regressions).

- [ ] **Step 5: Commit**

```bash
git add manager_backend/features/account/ tests/manager/test_account.py
git commit -m "feat(account): register bridge -> cloud signup + install trial entitlement"
```

---

### Task 6: Frontend — `accountRegister` API surface

**Files:**
- Modify: `manager/frontend/src/types/api.ts`, `api/adapter.ts`, `api/real.ts`, `mocks/mockApi.ts`, `features/account/api.ts`

**Interfaces:**
- Produces: `LicenseStatus.trial_end?: number | null`; `api.accountRegister(payload: EmailPasswordRequest): Promise<LicenseStatus>`; `useAccountRegister()` hook.

- [ ] **Step 1: Add the type field** — in `manager/frontend/src/types/api.ts`, add to `LicenseStatus` (after `grace_deadline`):
```ts
  trial_end?: number | null;
```
(Optional, so existing `LicenseStatus` literals in mocks/tests don't need changes.)

- [ ] **Step 2: Adapter method** — in `manager/frontend/src/api/adapter.ts`, add to the account/license block (after `accountActivate`):
```ts
  accountRegister(payload: EmailPasswordRequest): Promise<LicenseStatus>;
```
(`EmailPasswordRequest` and `LicenseStatus` are already imported there.)

- [ ] **Step 3: Real adapter** — in `manager/frontend/src/api/real.ts`, add (after `accountActivate`):
```ts
  accountRegister: (payload: EmailPasswordRequest) =>
    apiRequest<LicenseStatus>('/account/register', { method: 'POST', body: payload }),
```

- [ ] **Step 4: Mock adapter** — in `manager/frontend/src/mocks/mockApi.ts`, add (after `accountActivate`):
```ts
  async accountRegister(payload: EmailPasswordRequest): Promise<LicenseStatus> {
    await delay(160);
    mockStore.account = { cloud_configured: true, signed_in: true, email: payload.email };
    mockStore.license = {
      state: 'active',
      allowed: true,
      plan: 'trial',
      features: [],
      expires_at: null,
      grace_deadline: null,
      trial_end: null,
      detail: null,
    };
    return mockStore.license;
  },
```

- [ ] **Step 5: Hook** — in `manager/frontend/src/features/account/api.ts`, add:
```ts
export function useAccountRegister() {
  const refresh = useRefreshGate();
  return useMutation({
    mutationFn: (payload: EmailPasswordRequest) => api.accountRegister(payload),
    onSuccess: refresh,
  });
}
```

- [ ] **Step 6: Verify typecheck**

Run: `npm --prefix manager/frontend run typecheck`
Expected: clean (mock + real both satisfy the extended `ApiAdapter`).

- [ ] **Step 7: Commit**

```bash
git add manager/frontend/src/types/api.ts manager/frontend/src/api/adapter.ts manager/frontend/src/api/real.ts manager/frontend/src/mocks/mockApi.ts manager/frontend/src/features/account/api.ts
git commit -m "feat(frontend): accountRegister API surface (real + mock) + useAccountRegister"
```

---

### Task 7: Frontend — `SignUpPanel` + toggle + i18n + test

**Files:**
- Modify: `manager/frontend/src/features/account/LicenseScreen.tsx`, `i18n/en.ts`, `i18n/vi.ts`
- Test: `manager/frontend/src/features/account/SignUpPanel.test.tsx` (create)

**Interfaces:**
- Consumes: `useAccountRegister` (Task 6); the `SignInPanel`/`Field`/`Input`/`Button`/`PanelHeading` patterns already in `LicenseScreen.tsx`; the confirm-password validation pattern from `AuthGate.tsx`.
- Produces: an exported `SignUpPanel`; a Sign in⇄Sign up toggle in the signed-out branch of `LicenseScreen`.

- [ ] **Step 1: Add i18n keys** — add to BOTH `manager/frontend/src/i18n/en.ts` and `vi.ts` (flat dot-keys; `vi` must define the same keys or the build fails). English:
```ts
  'account.signUp': 'Create account',
  'account.signUpTitle': 'Start your 30-day trial',
  'account.signUpSubtitle': 'Create a Plasma account — no card required. Your trial unlocks profile launches for 30 days.',
  'account.needAccount': "New to Plasma? Start a 30-day free trial",
  'account.haveAccount': 'Already have an account? Sign in',
```
Vietnamese (same keys):
```ts
  'account.signUp': 'Tạo tài khoản',
  'account.signUpTitle': 'Bắt đầu dùng thử 30 ngày',
  'account.signUpSubtitle': 'Tạo tài khoản Plasma — không cần thẻ. Bản dùng thử mở khóa khởi chạy hồ sơ trong 30 ngày.',
  'account.needAccount': 'Mới dùng Plasma? Bắt đầu dùng thử miễn phí 30 ngày',
  'account.haveAccount': 'Đã có tài khoản? Đăng nhập',
```
(Reuse the existing `auth.email`, `auth.password`, `auth.confirmPassword`, `auth.mismatch`, `auth.passwordHint` keys — do not duplicate them.)

- [ ] **Step 2: Write the failing test** (`manager/frontend/src/features/account/SignUpPanel.test.tsx`)
```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { SignUpPanel } from './LicenseScreen';
import { api } from '@/api';
import type { LicenseStatus } from '@/types/api';

const LICENSE: LicenseStatus = {
  state: 'unlicensed', allowed: false, plan: null, features: [],
  expires_at: null, grace_deadline: null, detail: null,
};

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SignUpPanel license={LICENSE} onSwitch={() => {}} />
    </QueryClientProvider>,
  );
}

describe('SignUpPanel', () => {
  it('blocks submit when the passwords do not match', async () => {
    const spy = vi.spyOn(api, 'accountRegister');
    renderPanel();
    await userEvent.type(screen.getByLabelText(/email/i), 'a@b.co');
    const [pw, confirm] = screen.getAllByLabelText(/password/i);
    await userEvent.type(pw, 'correct horse battery staple');
    await userEvent.type(confirm, 'different password entirely');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));
    expect(spy).not.toHaveBeenCalled();
  });

  it('registers when the form is valid', async () => {
    const spy = vi.spyOn(api, 'accountRegister').mockResolvedValue({ ...LICENSE, state: 'active', allowed: true, plan: 'trial' });
    renderPanel();
    await userEvent.type(screen.getByLabelText(/email/i), 'a@b.co');
    const [pw, confirm] = screen.getAllByLabelText(/password/i);
    await userEvent.type(pw, 'correct horse battery staple');
    await userEvent.type(confirm, 'correct horse battery staple');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({ email: 'a@b.co', password: 'correct horse battery staple' }),
    );
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `npm --prefix manager/frontend run test -- src/features/account/SignUpPanel.test.tsx`
Expected: FAIL — `SignUpPanel` is not exported from `./LicenseScreen`.

- [ ] **Step 4: Implement** — in `manager/frontend/src/features/account/LicenseScreen.tsx`.

Add `useState` to the React import and `useAccountRegister` to the `./api` import. Change the signed-out branch of `LicenseScreen` to toggle between panels:
```tsx
// inside LicenseScreen, replace the `<SignInPanel license={license} />` branch:
          ) : (
            <SignedOut license={license} />
          )}
```
Add the `SignedOut` wrapper + `SignUpPanel` (exported) at the bottom of the file:
```tsx
function SignedOut({ license }: { license: LicenseStatus }) {
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const t = useT();
  return mode === 'signin' ? (
    <div className="space-y-3">
      <SignInPanel license={license} />
      <button
        type="button"
        className="w-full text-center text-2xs font-medium text-ink-muted transition hover:text-ink"
        onClick={() => setMode('signup')}
      >
        {t('account.needAccount')}
      </button>
    </div>
  ) : (
    <SignUpPanel license={license} onSwitch={() => setMode('signin')} />
  );
}

interface SignUpValues {
  email: string;
  password: string;
  confirm: string;
}

export function SignUpPanel({
  license,
  onSwitch,
}: {
  license: LicenseStatus;
  onSwitch: () => void;
}) {
  const t = useT();
  const registerMut = useAccountRegister();
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<SignUpValues>({ defaultValues: { email: '', password: '', confirm: '' } });

  const onSubmit = handleSubmit((values) =>
    registerMut.mutate({ email: values.email, password: values.password }),
  );
  const serverError = registerMut.error as ApiError | null;

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-line bg-surface p-6 shadow-panel">
        <div className="mb-4">
          <div className="mb-1.5 flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-accent" />
            <h1 className="font-display text-lg font-semibold text-ink">{t('account.signUpTitle')}</h1>
          </div>
          <p className="text-[13px] leading-relaxed text-ink-muted">{t('account.signUpSubtitle')}</p>
        </div>
        <form onSubmit={onSubmit} className="space-y-3">
          <Field label={t('auth.email')} error={errors.email && t('account.required')}>
            <Input
              type="email"
              autoComplete="username"
              autoFocus
              {...register('email', { required: true })}
              invalid={Boolean(errors.email)}
            />
          </Field>
          <Field
            label={t('auth.password')}
            hint={t('auth.passwordHint')}
            error={errors.password && t('auth.passwordHint')}
          >
            <Input
              type="password"
              autoComplete="new-password"
              {...register('password', { required: true, minLength: 12 })}
              invalid={Boolean(errors.password)}
            />
          </Field>
          <Field label={t('auth.confirmPassword')} error={errors.confirm && t('auth.mismatch')}>
            <Input
              type="password"
              autoComplete="new-password"
              {...register('confirm', { validate: (value) => value === watch('password') })}
              invalid={Boolean(errors.confirm)}
            />
          </Field>
          {serverError && <p className="text-2xs text-danger">{serverError.message}</p>}
          <Button type="submit" variant="primary" className="w-full" loading={registerMut.isPending}>
            {t('account.signUp')}
          </Button>
        </form>
      </div>
      <button
        type="button"
        className="w-full text-center text-2xs font-medium text-ink-muted transition hover:text-ink"
        onClick={onSwitch}
      >
        {t('account.haveAccount')}
      </button>
    </div>
  );
}
```
`ShieldCheck` is already imported in this file; add `useState` (from `react`) and `useAccountRegister` (from `./api`) to the existing imports.

- [ ] **Step 5: Run to verify it passes + full checks**

Run: `npm --prefix manager/frontend run test -- src/features/account/SignUpPanel.test.tsx`
Expected: PASS.
Run: `npm --prefix manager/frontend run typecheck` → clean.
Run: `npm --prefix manager/frontend run test` → all pass.
Run: `npm --prefix manager/frontend run build` → succeeds.

- [ ] **Step 6: Commit**

```bash
git add manager/frontend/src/features/account/ manager/frontend/src/i18n/en.ts manager/frontend/src/i18n/vi.ts
git commit -m "feat(frontend): SignUpPanel + Sign in/Sign up toggle + i18n"
```

---

## Self-Review

**Spec coverage:**
- Atomic `POST /auth/signup` (active user + trial key `now+30d` + device attach + session + redeem → session+entitlement) → Tasks 2–3. ✓
- 30-day mechanism (`key.expires_at` + `trial_end` claim + state-machine hard-cap) → Tasks 1, 4. ✓
- No email verification (account created `active`) → Task 2 (`status="active"`, no `EmailVerification`). ✓
- Desktop `CloudClient.register` / `AccountService.register` / `/account/register` / `RegisterRequest` → Task 5. ✓
- `SignUpPanel` + confirm-client-only + toggle + `useAccountRegister` + adapter/real/mock + type + i18n → Tasks 6–7. ✓
- Error handling (`email_taken`, short password) → Tasks 3 (422 / `email_taken`), 5 (`cloud_email_taken`). ✓
- Testing across all three layers (service + API + state-machine + component) → every task. ✓
- **Deviation from spec:** the trial Plan is created by `ensure_trial_plan` (get-or-create in the signup service) instead of a seed migration — self-contained, works on fresh DBs, and testable without migrations. Noted in Global Constraints / Task 2.
- **Deviation from spec:** `accountRegister` reuses `EmailPasswordRequest` instead of a new `AccountRegisterRequest` (identical shape; DRY). `trial_end` on the frontend `LicenseStatus` is optional to avoid fixture churn.

**Placeholder scan:** none — every step has runnable code + commands.

**Type consistency:** `signup_trial`/`SignupResult`/`ensure_trial_plan`/`TRIAL_PLAN_ID` used identically across Tasks 2–3; `trial_end` claim (Task 1) → read by `evaluate_license` (Task 4) → surfaced by `LicenseStatusRead` (Task 4) → typed on the frontend `LicenseStatus` (Task 6); `CloudClient.register`/`AccountService.register`/`accountRegister`/`useAccountRegister` consistent across Tasks 5–7. `SignupResponse` fields (`access_token, refresh_token, expires_in, entitlement_token`) match what `CloudClient.register` reads (`refresh_token`, `entitlement_token`).

**Out of scope (future specs):** email verification + real email provider, paid conversion, anti-abuse (rate limits / one-trial-per-device).
