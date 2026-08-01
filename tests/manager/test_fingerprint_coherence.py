from __future__ import annotations

from copy import deepcopy

import pytest

from manager_backend.features.profiles.fingerprint_coherence import (
    validate_fingerprint_coherence,
)


WINDOWS_UA_131 = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
LINUX_UA_131 = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _codes(result):
    return [finding["code"] for finding in result["findings"]]


def test_non_windows_custom_user_agent_is_an_error():
    result = validate_fingerprint_coherence(
        {"user_agent_mode": "custom", "custom_user_agent": LINUX_UA_131}
    )

    assert result["status"] == "error"
    assert result["findings"] == [
        {
            "code": "ua.platform_mismatch",
            "severity": "error",
            "field": "custom_user_agent",
            "message": "Custom user agent must identify Windows.",
        }
    ]


def test_custom_user_agent_major_must_match_pinned_browser_major():
    result = validate_fingerprint_coherence(
        {
            "browser_version_mode": "pinned",
            "browser_version": "132.0.6834.83",
            "user_agent_mode": "custom",
            "custom_user_agent": WINDOWS_UA_131,
        }
    )

    assert result["status"] == "error"
    assert _codes(result) == ["ua.version_mismatch"]
    assert result["findings"][0]["field"] == "custom_user_agent"


@pytest.mark.parametrize(
    ("vendor", "renderer"),
    [
        ("NVIDIA Corporation", "ANGLE (Intel, Intel Iris Xe Graphics)"),
        ("Advanced Micro Devices, Inc.", "ANGLE (NVIDIA, GeForce RTX 3060)"),
        ("Intel Inc.", "ANGLE (AMD, Radeon RX 7600)"),
    ],
)
def test_recognizable_gpu_vendor_must_match_renderer_family(vendor, renderer):
    result = validate_fingerprint_coherence(
        {"gpu_vendor": vendor, "gpu_renderer": renderer}
    )

    assert result["status"] == "error"
    assert _codes(result) == ["gpu.vendor_renderer_mismatch"]
    assert result["findings"][0]["field"] == "gpu_renderer"


def test_direct3d_renderer_is_an_error_for_non_windows_user_agent():
    result = validate_fingerprint_coherence(
        {
            "user_agent_mode": "custom",
            "custom_user_agent": LINUX_UA_131,
            "gpu_vendor": "NVIDIA Corporation",
            "gpu_renderer": "ANGLE (NVIDIA, GeForce RTX 3060, Direct3D11)",
        }
    )

    assert result["status"] == "error"
    assert _codes(result) == ["ua.platform_mismatch", "gpu.platform_mismatch"]


@pytest.mark.parametrize("renderer", ["Apple M2", "ANGLE Metal Renderer: Apple M2"])
def test_apple_or_metal_renderer_is_an_error_for_windows_persona(renderer):
    result = validate_fingerprint_coherence(
        {"gpu_vendor": "Apple Inc.", "gpu_renderer": renderer}
    )

    assert result["status"] == "error"
    assert _codes(result) == ["gpu.platform_mismatch"]


def test_manual_timezone_mismatch_with_verified_proxy_is_a_warning():
    result = validate_fingerprint_coherence(
        {
            "location": {"geo_mode": "manual", "timezone": "Europe/London"},
            "proxy_verified": True,
            "proxy_timezone": "Asia/Ho_Chi_Minh",
        }
    )

    assert result["status"] == "warning"
    assert result["findings"] == [
        {
            "code": "geo.timezone_mismatch",
            "severity": "warning",
            "field": "location.timezone",
            "message": "Manual timezone differs from the verified proxy timezone.",
        }
    ]


def test_manual_locale_mismatch_with_verified_proxy_country_is_a_warning():
    result = validate_fingerprint_coherence(
        {
            "location": {"geo_mode": "manual", "locale": "en-US"},
            "proxy_verified": True,
            "proxy_country": "VN",
        }
    )

    assert result["status"] == "warning"
    assert result["findings"] == [
        {
            "code": "geo.locale_mismatch",
            "severity": "warning",
            "field": "location.locale",
            "message": "Manual locale differs from the verified proxy country.",
        }
    ]


def test_manual_locale_with_matching_country_subtag_is_plausible():
    result = validate_fingerprint_coherence(
        {
            "location": {"geo_mode": "manual", "locale": "fr-CA"},
            "proxy_verified": True,
            "proxy_country": "CA",
        }
    )

    assert result == {"status": "coherent", "findings": []}


def test_coherent_profile_has_no_findings():
    profile = {
        "browser_version_mode": "pinned",
        "browser_version": "131.0.6778.86",
        "user_agent_mode": "custom",
        "custom_user_agent": WINDOWS_UA_131,
        "gpu_vendor": "NVIDIA Corporation",
        "gpu_renderer": "ANGLE (NVIDIA, GeForce RTX 3060, Direct3D11)",
        "location": {
            "geo_mode": "manual",
            "timezone": "Asia/Ho_Chi_Minh",
            "locale": "vi-VN",
        },
        "proxy_verified": True,
        "proxy_timezone": "Asia/Ho_Chi_Minh",
        "proxy_country": "VN",
    }

    assert validate_fingerprint_coherence(profile) == {
        "status": "coherent",
        "findings": [],
    }


def test_findings_follow_stable_rule_order():
    profile = {
        "browser_version_mode": "pinned",
        "browser_version": "132.0.6834.83",
        "user_agent_mode": "custom",
        "custom_user_agent": LINUX_UA_131,
        "gpu_vendor": "Intel Inc.",
        "gpu_renderer": "ANGLE (NVIDIA, GeForce RTX 3060, Direct3D11)",
        "location": {
            "geo_mode": "manual",
            "timezone": "Europe/London",
            "locale": "en-GB",
        },
        "proxy_verified": True,
        "proxy_timezone": "Asia/Ho_Chi_Minh",
        "proxy_country": "VN",
    }

    expected = [
        "ua.platform_mismatch",
        "ua.version_mismatch",
        "gpu.vendor_renderer_mismatch",
        "gpu.platform_mismatch",
        "geo.timezone_mismatch",
        "geo.locale_mismatch",
    ]
    assert _codes(validate_fingerprint_coherence(profile)) == expected
    assert _codes(validate_fingerprint_coherence(profile)) == expected


def test_validation_does_not_mutate_input():
    profile = {
        "user_agent_mode": "custom",
        "custom_user_agent": LINUX_UA_131,
        "location": {"geo_mode": "manual", "locale": "en-US"},
        "proxy_verified": True,
        "proxy_country": "VN",
    }
    original = deepcopy(profile)

    validate_fingerprint_coherence(profile)

    assert profile == original
