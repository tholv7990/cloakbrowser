from __future__ import annotations

import platform as _platform
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from cloakbrowser._version import __version__ as cloakbrowser_version
from cloakbrowser.config import get_chromium_version

from ...dependencies import get_session
from ..runtime.service import count_active_runtimes
from .schemas import AppBootstrap, AppVersion


router = APIRouter(prefix="/app", tags=["application"])
SessionDependency = Annotated[Session, Depends(get_session)]


@router.get("/bootstrap", response_model=AppBootstrap, operation_id="app_bootstrap")
def bootstrap(request: Request, session: SessionDependency) -> AppBootstrap:
    # The fingerprint OS mirrors the patched binary's rule: native macOS on a
    # Mac, Windows everywhere else (Linux hosts spoof Windows). Cross-OS spoofing
    # is a detectable font/GPU mismatch, so the OS tracks the host, not a choice.
    fingerprint_os = "macos" if _platform.system() == "Darwin" else "windows"
    return AppBootstrap(
        api_version="v1",
        platform=fingerprint_os,
        owner_email=request.state.owner.email,
        capabilities={
            "authentication": True,
            "profiles": True,
            "catalogs": True,
            "proxy_management": True,
            "browser_runtime": True,
            "fingerprint_diagnostics": False,
            "settings": True,
            "resources": True,
            "media": True,
            "automation": True,
            "shopify_builder": True,
        },
        running_session_count=count_active_runtimes(session),
    )


@router.get("/version", response_model=AppVersion, operation_id="app_version")
def version() -> AppVersion:
    return AppVersion(
        manager_api_version="1.0.0",
        cloakbrowser_version=cloakbrowser_version,
        chromium_version=get_chromium_version(),
    )
