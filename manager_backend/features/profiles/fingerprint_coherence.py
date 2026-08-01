from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from ..proxies.service import _LOCALE_BY_COUNTRY


Finding = dict[str, str]
Rule = Callable[[Mapping[str, Any]], Finding | None]

_CHROMIUM_MAJOR_RE = re.compile(r"(?:Chrome|Chromium)/(\d+)", re.IGNORECASE)


def _finding(code: str, severity: str, field: str, message: str) -> Finding:
    return {
        "code": code,
        "severity": severity,
        "field": field,
        "message": message,
    }


def _custom_user_agent(profile: Mapping[str, Any]) -> str | None:
    value = profile.get("custom_user_agent")
    return value if isinstance(value, str) and value else None


def _location(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    value = profile.get("location")
    return value if isinstance(value, Mapping) else {}


def _ua_platform_rule(profile: Mapping[str, Any]) -> Finding | None:
    user_agent = _custom_user_agent(profile)
    if user_agent is not None and "windows nt" not in user_agent.casefold():
        return _finding(
            "ua.platform_mismatch",
            "error",
            "custom_user_agent",
            "Custom user agent must identify Windows.",
        )
    return None


def _ua_version_rule(profile: Mapping[str, Any]) -> Finding | None:
    if profile.get("browser_version_mode") != "pinned":
        return None
    browser_version = profile.get("browser_version")
    user_agent = _custom_user_agent(profile)
    if not isinstance(browser_version, str) or user_agent is None:
        return None
    match = _CHROMIUM_MAJOR_RE.search(user_agent)
    if match is not None and match.group(1) != browser_version.split(".", 1)[0]:
        return _finding(
            "ua.version_mismatch",
            "error",
            "custom_user_agent",
            "Custom user agent Chromium major must match the pinned browser major.",
        )
    return None


def _gpu_family(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.casefold()
    if "nvidia" in normalized:
        return "nvidia"
    if (
        re.search(r"\bamd\b", normalized)
        or "advanced micro devices" in normalized
        or re.search(r"\bati(?: technologies)?\b", normalized)
    ):
        return "amd"
    if "intel" in normalized:
        return "intel"
    return None


def _gpu_vendor_renderer_rule(profile: Mapping[str, Any]) -> Finding | None:
    vendor_family = _gpu_family(profile.get("gpu_vendor"))
    renderer_family = _gpu_family(profile.get("gpu_renderer"))
    if vendor_family is not None and renderer_family is not None and vendor_family != renderer_family:
        return _finding(
            "gpu.vendor_renderer_mismatch",
            "error",
            "gpu_renderer",
            "GPU vendor and renderer identify different hardware families.",
        )
    return None


def _gpu_platform_rule(profile: Mapping[str, Any]) -> Finding | None:
    renderer = profile.get("gpu_renderer")
    if not isinstance(renderer, str):
        return None
    normalized = renderer.casefold()
    user_agent = _custom_user_agent(profile)
    declares_windows = user_agent is None or "windows nt" in user_agent.casefold()
    direct3d_on_non_windows = "direct3d" in normalized and not declares_windows
    apple_or_metal_on_windows = "apple" in normalized or "metal" in normalized
    if direct3d_on_non_windows or apple_or_metal_on_windows:
        return _finding(
            "gpu.platform_mismatch",
            "error",
            "gpu_renderer",
            "GPU renderer is incompatible with the Windows browser persona.",
        )
    return None


def _geo_timezone_rule(profile: Mapping[str, Any]) -> Finding | None:
    location = _location(profile)
    timezone = location.get("timezone")
    proxy_timezone = profile.get("proxy_timezone")
    if (
        location.get("geo_mode") == "manual"
        and profile.get("proxy_verified") is True
        and isinstance(timezone, str)
        and isinstance(proxy_timezone, str)
        and timezone.casefold() != proxy_timezone.casefold()
    ):
        return _finding(
            "geo.timezone_mismatch",
            "warning",
            "location.timezone",
            "Manual timezone differs from the verified proxy timezone.",
        )
    return None


def _locale_region(locale: str) -> str | None:
    for subtag in locale.split("-")[1:]:
        if (len(subtag) == 2 and subtag.isalpha()) or (
            len(subtag) == 3 and subtag.isdecimal()
        ):
            return subtag.upper()
    return None


def _geo_locale_rule(profile: Mapping[str, Any]) -> Finding | None:
    location = _location(profile)
    locale = location.get("locale")
    country = profile.get("proxy_country")
    if (
        location.get("geo_mode") != "manual"
        or profile.get("proxy_verified") is not True
        or not isinstance(locale, str)
        or not isinstance(country, str)
    ):
        return None
    expected_locale = _LOCALE_BY_COUNTRY.get(country.upper())
    expected_region = _locale_region(expected_locale) if expected_locale is not None else None
    locale_region = _locale_region(locale)
    if expected_region is not None and locale_region is not None and locale_region != expected_region:
        return _finding(
            "geo.locale_mismatch",
            "warning",
            "location.locale",
            "Manual locale differs from the verified proxy country.",
        )
    return None


_RULES: tuple[Rule, ...] = (
    _ua_platform_rule,
    _ua_version_rule,
    _gpu_vendor_renderer_rule,
    _gpu_platform_rule,
    _geo_timezone_rule,
    _geo_locale_rule,
)


def validate_fingerprint_coherence(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Return deterministic coherence findings without changing ``profile``."""

    findings = [finding for rule in _RULES if (finding := rule(profile)) is not None]
    if any(finding["severity"] == "error" for finding in findings):
        status = "error"
    elif findings:
        status = "warning"
    else:
        status = "coherent"
    return {"status": status, "findings": findings}
