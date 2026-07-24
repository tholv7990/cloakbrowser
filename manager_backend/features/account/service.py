"""Account service: the desktop<->cloud bridge that feeds license enforcement.

Flow: login (email/password + this device) -> a rotating refresh token kept in the OS
credential store; activate (redeem a key) and refresh-entitlement exchange a freshly
rotated access token for a signed entitlement, which is verified + cached by the
license service. A revoked/expired key makes the cloud refuse to re-issue, so the
cached entitlement lapses and the launch gate blocks. Secrets are never logged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ...config import ManagerSettings
from ...errors import ManagerError
from ..license import service as license_service
from ..license.service import LicenseStatus
from .cloud_client import CloudClient, CloudClientError
from .device import get_or_create_device
from .secrets import SecretStore

REFRESH_REF = "cloud-refresh-token"

# Cloud error code -> (safe message, http status). Unknown codes fall through to a
# generic message so we never surface internal detail.
_CLOUD_ERRORS = {
    "invalid_credentials": ("Incorrect email or password.", 401),
    "account_unverified": ("Verify your email address first.", 403),
    "account_suspended": ("This account is suspended.", 403),
    "invalid_refresh": ("Your session expired. Sign in again.", 401),
    "refresh_reuse": ("Your session expired. Sign in again.", 401),
    "refresh_expired": ("Your session expired. Sign in again.", 401),
    "device_revoked": ("This device was removed. Sign in again.", 403),
    "device_cap": ("You have reached your device limit.", 409),
    "throttled": ("Too many attempts. Try again shortly.", 429),
    "invalid_key": ("That activation key is not valid.", 404),
    "key_suspended": ("That activation key is suspended.", 403),
    "key_revoked": ("That activation key was revoked.", 403),
    "key_expired": ("That activation key has expired.", 403),
    "key_exhausted": ("That activation key has no uses left.", 409),
    "not_entitled": ("No active license for this device.", 403),
    "email_taken": ("An account with this email already exists.", 409),
}


@dataclass
class AccountStatus:
    cloud_configured: bool
    signed_in: bool
    email: str | None = None


def _manager_error(error: CloudClientError) -> ManagerError:
    message, status = _CLOUD_ERRORS.get(
        error.code, ("The license server could not complete the request.", 502)
    )
    # Prefix keeps the code namespaced + fixed/safe for the UI.
    return ManagerError(f"cloud_{error.code}", message, status)


class AccountService:
    def __init__(
        self,
        settings: ManagerSettings,
        *,
        secret_store: SecretStore,
        client_factory=None,
    ):
        self._settings = settings
        self._secrets = secret_store
        self._client_factory = client_factory or (lambda base: CloudClient(base))

    # --- helpers --------------------------------------------------------------

    def _client(self) -> CloudClient:
        if not self._settings.cloud_base_url:
            raise ManagerError(
                "cloud_not_configured", "This build has no license server configured.", 503
            )
        return self._client_factory(self._settings.cloud_base_url)

    @property
    def _state_path(self):
        return self._settings.data_root / "account.json"

    def _load_state(self) -> dict:
        path = self._state_path
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}

    def _save_state(self, state: dict) -> None:
        self._settings.data_root.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(state), encoding="utf-8")

    def _fresh_access(self) -> str:
        """Rotate the stored refresh token and return a fresh access token."""
        refresh = self._secrets.get(REFRESH_REF)
        if not refresh:
            raise ManagerError("not_signed_in", "Sign in to continue.", 401)
        try:
            tokens = self._client().refresh_session(refresh_token=refresh)
        except CloudClientError as error:
            raise _manager_error(error) from error
        self._secrets.put(REFRESH_REF, tokens["refresh_token"])
        return tokens["access_token"]

    # --- API ------------------------------------------------------------------

    def status(self) -> AccountStatus:
        return AccountStatus(
            cloud_configured=bool(self._settings.cloud_base_url),
            signed_in=self._secrets.get(REFRESH_REF) is not None,
            email=self._load_state().get("email"),
        )

    def login(self, *, email: str, password: str) -> AccountStatus:
        client = self._client()
        device = get_or_create_device(self._secrets)
        try:
            tokens = client.login(email=email, password=password, device=device)
        except CloudClientError as error:
            raise _manager_error(error) from error
        self._secrets.put(REFRESH_REF, tokens["refresh_token"])
        self._save_state({"email": email})
        return self.status()

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

    def activate(self, *, activation_key: str) -> LicenseStatus:
        access = self._fresh_access()
        try:
            token = self._client().redeem_key(
                access_token=access, activation_key=activation_key
            )
        except CloudClientError as error:
            raise _manager_error(error) from error
        return license_service.install_entitlement(self._settings, token)

    def refresh_entitlement(self) -> LicenseStatus:
        access = self._fresh_access()
        try:
            token = self._client().refresh_entitlement(access_token=access)
        except CloudClientError as error:
            raise _manager_error(error) from error
        return license_service.install_entitlement(self._settings, token)

    def logout(self) -> AccountStatus:
        refresh = self._secrets.get(REFRESH_REF)
        if refresh and self._settings.cloud_base_url:
            try:
                self._client().logout(refresh_token=refresh)
            except CloudClientError:
                pass  # best effort; we clear locally regardless
        self._secrets.delete(REFRESH_REF)
        self._save_state({})
        license_service.clear_entitlement(self._settings)
        return self.status()
