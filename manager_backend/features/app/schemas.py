from __future__ import annotations

from ...schemas.common import StrictModel


class AppCapabilities(StrictModel):
    authentication: bool
    profiles: bool
    catalogs: bool
    proxy_management: bool
    browser_runtime: bool
    fingerprint_diagnostics: bool
    settings: bool
    resources: bool
    media: bool


class AppBootstrap(StrictModel):
    api_version: str
    platform: str
    owner_email: str
    capabilities: AppCapabilities
    running_session_count: int


class AppVersion(StrictModel):
    manager_api_version: str
    cloakbrowser_version: str
    chromium_version: str
