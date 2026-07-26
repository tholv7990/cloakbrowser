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

