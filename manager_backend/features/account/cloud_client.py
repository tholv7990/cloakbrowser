"""Thin HTTP client for the Plasma cloud (login / session / license).

Backend-to-backend from the desktop's local FastAPI, so credentials never reach the
WebView. The cloud returns a fixed ``{"error": <code>}`` envelope on failure, which
we surface as ``CloudClientError(code, status)`` for the service layer to map to a
safe ManagerError. Nothing here logs a token, password, key, or refresh secret.
"""

from __future__ import annotations

from .device import DeviceIdentity


class CloudClientError(Exception):
    def __init__(self, code: str, status: int):
        self.code = code
        self.status = status
        super().__init__(code)


class CloudClient:
    def __init__(self, base_url: str, *, http=None):
        self._base = base_url.rstrip("/")
        if http is None:
            import httpx

            http = httpx.Client(timeout=15.0)
        self._http = http

    def _post(self, path: str, payload: dict, *, token: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = self._http.post(self._base + path, json=payload, headers=headers)
        if response.status_code // 100 != 2:
            code = "cloud_error"
            try:
                body = response.json()
                if isinstance(body, dict) and isinstance(body.get("error"), str):
                    code = body["error"]
            except Exception:
                pass
            raise CloudClientError(code, response.status_code)
        return response.json() if response.content else {}

    # --- auth / session -------------------------------------------------------

    def login(self, *, email: str, password: str, device: DeviceIdentity) -> dict:
        """Authenticate + attach this device -> {access_token, refresh_token, expires_in}."""
        return self._post(
            "/auth/token",
            {
                "email": email,
                "password": password,
                "device_public_key": device.public_key_b64,
                "device_signature": device.signature_b64(),
                "device_name": "Plasma Desktop",
            },
        )

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

    def refresh_session(self, *, refresh_token: str) -> dict:
        """Rotate the refresh token -> a fresh {access_token, refresh_token, ...}."""
        return self._post("/auth/token/refresh", {"refresh_token": refresh_token})

    def logout(self, *, refresh_token: str) -> None:
        self._post("/auth/logout", {"refresh_token": refresh_token})

    # --- license --------------------------------------------------------------

    def redeem_key(self, *, access_token: str, activation_key: str) -> str:
        """Redeem an activation key -> signed entitlement token."""
        body = self._post(
            "/activation/redeem", {"activation_key": activation_key}, token=access_token
        )
        return body["entitlement_token"]

    def refresh_entitlement(self, *, access_token: str) -> str:
        """Re-issue the entitlement for this device -> signed entitlement token.
        Fails (key_revoked / key_expired / device_revoked) once the key is dead."""
        body = self._post("/entitlement/refresh", {}, token=access_token)
        return body["entitlement_token"]
