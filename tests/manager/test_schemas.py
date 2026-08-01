from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from manager_backend.features.profiles.schemas import (
    BehaviorSettings,
    LocationSettings,
    ProfileCreate,
    ProfilePatch,
    ProfileRead,
    ProfileValidationDraft,
    WindowSettings,
)
from manager_backend.fingerprints import build_fingerprint_identity


@pytest.mark.parametrize(
    ("field", "value"),
    [("platform", "macos"), ("password", "secret"), ("two_factor_key", "ABC123")],
)
def test_profile_rejects_unsupported_or_vault_fields(field, value):
    with pytest.raises(ValidationError):
        ProfileCreate(name="Account A", **{field: value})


def test_seed_must_be_unsigned_64_bit_decimal():
    with pytest.raises(ValidationError):
        ProfileCreate(name="A", fingerprint_seed="18446744073709551616")
    with pytest.raises(ValidationError):
        ProfileCreate(name="A", fingerprint_seed="-1")


def test_manual_geolocation_requires_coordinates():
    with pytest.raises(ValidationError):
        LocationSettings(geolocation_mode="manual")


def test_non_manual_geolocation_rejects_coordinates():
    with pytest.raises(ValidationError):
        LocationSettings(geolocation_mode="ask", latitude=10, longitude=20)


def test_webrtc_disabled_mode_is_rejected():
    # "disabled" was never enforced at launch (F-001); retired so the UI can't
    # promise a WebRTC-off behavior the engine does not deliver.
    with pytest.raises(ValidationError):
        LocationSettings(webrtc_mode="disabled")


def test_webrtc_supported_modes_are_accepted():
    assert LocationSettings(webrtc_mode="proxy").webrtc_mode == "proxy"
    assert LocationSettings(webrtc_mode="direct").webrtc_mode == "direct"


def test_custom_window_requires_dimensions():
    with pytest.raises(ValidationError):
        WindowSettings(mode="custom")


def test_maximized_window_rejects_custom_dimensions():
    with pytest.raises(ValidationError):
        WindowSettings(mode="maximized", width=1280, height=720)


@pytest.mark.parametrize(("width", "height"), [(2560, 1080), (1920, 1440)])
def test_custom_window_exceeding_default_masked_screen_is_rejected(width, height):
    # F-015: a window larger than the spoofed 1920x1080 screen makes
    # outerWidth/innerWidth > screen.width — an impossible, detectable geometry.
    with pytest.raises(ValidationError):
        ProfileCreate(
            name="A",
            window={"mode": "custom", "width": width, "height": height},
        )


def test_custom_window_within_default_masked_screen_is_accepted():
    profile = ProfileCreate(
        name="A",
        window={"mode": "custom", "width": 1366, "height": 768},
    )
    assert (profile.window.width, profile.window.height) == (1366, 768)


def test_custom_window_cannot_exceed_smaller_explicit_masked_screen():
    with pytest.raises(ValidationError):
        ProfileCreate(
            name="A",
            screen_width=1366,
            screen_height=768,
            window={"mode": "custom", "width": 1920, "height": 1080},
        )


def test_larger_explicit_masked_screen_allows_containing_custom_window():
    profile = ProfileCreate(
        name="A",
        screen_width=2560,
        screen_height=1440,
        window={"mode": "custom", "width": 2400, "height": 1200},
    )

    assert (profile.window.width, profile.window.height) == (2400, 1200)


_WINDOWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
_MACOS_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)


def test_custom_user_agent_must_declare_windows():
    # F-008: a custom UA that contradicts the Windows-only platform is incoherent.
    with pytest.raises(ValidationError):
        ProfileCreate(name="A", user_agent_mode="custom", custom_user_agent=_MACOS_UA)


def test_windows_custom_user_agent_is_accepted():
    profile = ProfileCreate(name="A", user_agent_mode="custom", custom_user_agent=_WINDOWS_UA)
    assert profile.custom_user_agent == _WINDOWS_UA


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("humanize_enabled", True),
        ("hardware_concurrency_mode", "custom"),
        ("gpu_mode", "custom_vendor"),
        ("additional_args", ["--foo"]),
        ("ignore_https_errors", True),
        ("clear_cache_before_launch", True),
        ("restore_previous_tabs", False),
        ("download_directory_mode", "custom"),
    ],
)
def test_retired_behavior_fields_are_rejected(field, value):
    # F-006: stored but never applied; retired so the UI can't promise a behavior
    # the engine does not deliver.
    with pytest.raises(ValidationError):
        BehaviorSettings(**{field: value})


def test_window_color_scheme_is_rejected():
    with pytest.raises(ValidationError):
        WindowSettings(color_scheme="dark")


def test_fingerprint_seed_and_hash_are_stable():
    first = build_fingerprint_identity(seed="42")
    second = build_fingerprint_identity(seed="42")

    assert first.seed == second.seed == "42"
    assert first.revision == second.revision == 2
    assert first.config_hash == second.config_hash


def test_different_seeds_have_different_config_hashes():
    assert build_fingerprint_identity(seed="1").config_hash != build_fingerprint_identity(
        seed="2"
    ).config_hash


def test_operational_behavior_does_not_change_fingerprint_hash():
    # permissions is a runtime grant, not a fingerprint surface — it must not move
    # the identity hash.
    first = build_fingerprint_identity(seed="42", behavior=BehaviorSettings())
    second = build_fingerprint_identity(
        seed="42", behavior=BehaviorSettings(permissions={"camera": "allow"})
    )

    assert first.config_hash == second.config_hash


_FINGERPRINT_OVERRIDES = {
    "gpu_vendor": "Test GPU Vendor",
    "gpu_renderer": "Test GPU Renderer",
    "hardware_concurrency": 8,
    "device_memory": 16,
    "screen_width": 1920,
    "screen_height": 1080,
    "brand": "TestBrand",
}


def test_profile_accepts_and_normalizes_fingerprint_overrides():
    profile = ProfileCreate(
        name="A",
        gpu_vendor="  Test GPU Vendor  ",
        gpu_renderer="  Test GPU Renderer  ",
        hardware_concurrency=1,
        device_memory=1024,
        screen_width=320,
        screen_height=16384,
        brand="  TestBrand  ",
    )

    assert profile.gpu_vendor == "Test GPU Vendor"
    assert profile.gpu_renderer == "Test GPU Renderer"
    assert profile.hardware_concurrency == 1
    assert profile.device_memory == 1024
    assert profile.screen_width == 320
    assert profile.screen_height == 16384
    assert profile.brand == "TestBrand"


@pytest.mark.parametrize("field", ["gpu_vendor", "gpu_renderer", "brand"])
def test_profile_rejects_blank_fingerprint_override_strings(field):
    with pytest.raises(ValidationError):
        ProfileCreate(name="A", **{field: "   "})


@pytest.mark.parametrize(
    ("field", "value"),
    [("gpu_vendor", "v" * 257), ("gpu_renderer", "r" * 257), ("brand", "b" * 65)],
)
def test_profile_rejects_oversized_fingerprint_override_strings(field, value):
    with pytest.raises(ValidationError):
        ProfileCreate(name="A", **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hardware_concurrency", True),
        ("device_memory", 0),
        ("hardware_concurrency", 1025),
        ("screen_width", 319),
        ("screen_height", 16385),
    ],
)
def test_profile_rejects_invalid_fingerprint_override_integers(field, value):
    payload = {field: value}
    if field == "screen_width":
        payload["screen_height"] = 1080
    elif field == "screen_height":
        payload["screen_width"] = 1920
    with pytest.raises(ValidationError):
        ProfileCreate(name="A", **payload)


@pytest.mark.parametrize("schema", [ProfileCreate, ProfilePatch])
def test_profile_screens_must_be_supplied_as_a_pair(schema):
    values = {"name": "A"} if schema is ProfileCreate else {
        "expected_updated_at": datetime.now(timezone.utc)
    }
    with pytest.raises(ValidationError):
        schema(**values, screen_width=1920)
    with pytest.raises(ValidationError):
        schema(**values, screen_height=None)


@pytest.mark.parametrize(
    "schema_type", [ProfileCreate, ProfilePatch, ProfileRead, ProfileValidationDraft]
)
def test_fingerprint_override_json_schema_matches_runtime_validation(schema_type):
    schema = schema_type.model_json_schema()

    for field in ("gpu_vendor", "gpu_renderer", "brand"):
        string_schema = next(
            item
            for item in schema["properties"][field]["anyOf"]
            if item["type"] == "string"
        )
        assert string_schema["minLength"] == 1

    assert schema["dependentRequired"] == {
        "screen_width": ["screen_height"],
        "screen_height": ["screen_width"],
    }
    assert "screen_height" in schema["properties"]["screen_width"]["description"]
    assert "screen_width" in schema["properties"]["screen_height"]["description"]


@pytest.mark.parametrize(("field", "value"), _FINGERPRINT_OVERRIDES.items())
def test_each_fingerprint_override_changes_config_hash(field, value):
    baseline = build_fingerprint_identity(seed="42")
    changed = build_fingerprint_identity(seed="42", overrides={field: value})

    assert changed.config_hash != baseline.config_hash


def test_null_fingerprint_overrides_preserve_existing_identity_hash():
    baseline = build_fingerprint_identity(seed="42")
    with_null_overrides = build_fingerprint_identity(
        seed="42", overrides={field: None for field in _FINGERPRINT_OVERRIDES}
    )

    assert with_null_overrides == baseline


def test_pinned_version_older_than_bundled_is_rejected():
    # F-011 (partial, no false positives): you can never pin a build older than the
    # bundled free one. Full unresolvable-version rejection needs the cloud version list.
    with pytest.raises(ValidationError):
        ProfileCreate(
            name="A", browser_version_mode="pinned", browser_version="50.0.0.0"
        )


def test_pinned_current_or_newer_version_is_accepted():
    from cloakbrowser.config import get_chromium_version

    major = int(get_chromium_version().split(".")[0])
    at_bundled = ProfileCreate(
        name="A", browser_version_mode="pinned", browser_version=f"{major}.0.0.0"
    )
    assert at_bundled.browser_version == f"{major}.0.0.0"
    # A plausibly-newer Pro pin is allowed (full resolvability needs the server).
    newer = ProfileCreate(
        name="A", browser_version_mode="pinned", browser_version=f"{major + 4}.0.0.0"
    )
    assert newer.browser_version == f"{major + 4}.0.0.0"


def test_profile_defaults_are_safe_and_consistent():
    profile = ProfileCreate(name="  Account A  ")

    assert profile.name == "Account A"
    assert profile.fingerprint_preset == "consistent"
    assert profile.browser_version_mode == "installed"
    assert profile.user_agent_mode == "automatic"
    assert profile.window.mode == "maximized"
    assert profile.behavior.permissions == {}
    assert profile.startup_urls == []
    assert {
        field: getattr(profile, field) for field in _FINGERPRINT_OVERRIDES
    } == {field: None for field in _FINGERPRINT_OVERRIDES}


def test_profile_patch_requires_concurrency_token_and_tracks_only_provided_fields():
    with pytest.raises(ValidationError):
        ProfilePatch()

    expected_updated_at = datetime(2026, 7, 22, 12, 30, tzinfo=timezone.utc)
    patch = ProfilePatch(expected_updated_at=expected_updated_at)

    assert patch.expected_updated_at == expected_updated_at
    assert patch.model_fields_set == {"expected_updated_at"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", None),
        ("notes", None),
        ("pinned", None),
        ("startup_urls", None),
        ("location", None),
        ("window", None),
        ("behavior", None),
    ],
)
def test_profile_patch_rejects_explicit_null_for_non_nullable_fields(field, value):
    with pytest.raises(ValidationError):
        ProfilePatch(
            expected_updated_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
            **{field: value},
        )


def test_profile_patch_openapi_marks_only_concurrency_token_required():
    schema = ProfilePatch.model_json_schema()

    assert schema["required"] == ["expected_updated_at"]
    assert schema["properties"]["name"]["type"] == "string"
    assert {item["type"] for item in schema["properties"]["folder_id"]["anyOf"]} == {
        "string",
        "null",
    }
    assert "fingerprint_seed" not in schema["properties"]
