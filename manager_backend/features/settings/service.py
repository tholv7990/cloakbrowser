from __future__ import annotations

from pathlib import Path

from cloakbrowser.download import binary_info, check_for_pro_update, check_for_update
from cloakbrowser.license import (
    LicenseInfo,
    get_active_session_count,
    get_pro_latest_version,
    resolve_license_key,
    validate_license,
)

from ...config import ManagerSettings
from .schemas import LicenseSettingsRead, ManagerPreferences, SettingsRead


SESSION_LIMITS = {"solo": 3, "team": 20, "business": 200, "scale": 2000}


def _parts(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return ()


def build_settings_read(
    config: ManagerSettings, preferences: ManagerPreferences
) -> SettingsRead:
    facts = binary_info()
    key = resolve_license_key()
    license_info = validate_license(key) if key else None
    valid = bool(license_info and license_info.valid)
    plan = license_info.plan if license_info else None
    latest = get_pro_latest_version() if valid else facts.get("bundled_version")
    active = get_active_session_count(key) if key and valid else None
    current = str(facts.get("version") or "")
    return SettingsRead(
        **preferences.model_dump(),
        profile_root=str(config.profile_root),
        report_root=str(config.data_root / "reports"),
        browser={
            "name": "CloakBrowser Chromium",
            "version": current,
            "path": str(Path(str(facts["binary_path"]))),
            "platform": str(facts.get("platform") or "windows-x64"),
            "tier": facts.get("tier", "free"),
            "installed": bool(facts.get("installed")),
            "update_available": bool(latest and _parts(latest) > _parts(current)),
            "latest_version": latest,
        },
        license=LicenseSettingsRead(
            configured=key is not None,
            valid=license_info.valid if license_info else None,
            plan=plan,
            expires=license_info.expires if license_info else None,
            active_sessions=active,
            session_limit=SESSION_LIMITS.get(plan or ""),
        ),
    )


def update_entitled_binary() -> str | None:
    key = resolve_license_key()
    license_info = validate_license(key) if key else None
    if key and license_info and license_info.valid:
        return check_for_pro_update(key)
    return check_for_update()
