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

