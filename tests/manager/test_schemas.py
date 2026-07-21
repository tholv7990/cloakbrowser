from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from manager_backend.features.profiles.schemas import (
    BehaviorSettings,
    LocationSettings,
    ProfileCreate,
    ProfilePatch,
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


def test_custom_window_requires_dimensions():
    with pytest.raises(ValidationError):
        WindowSettings(mode="custom")


def test_maximized_window_rejects_custom_dimensions():
    with pytest.raises(ValidationError):
        WindowSettings(mode="maximized", width=1280, height=720)


def test_custom_hardware_concurrency_requires_value():
    with pytest.raises(ValidationError):
        BehaviorSettings(hardware_concurrency_mode="custom")


@pytest.mark.parametrize(
    "argument",
    [
        "--fingerprint=999",
        "--user-data-dir=C:/escape",
        "--proxy-server=socks5://secret",
        "--remote-debugging-port=9222",
        "--load-extension=C:/escape",
    ],
)
def test_manager_owned_chromium_arguments_are_rejected(argument):
    with pytest.raises(ValidationError):
        BehaviorSettings(additional_args=[argument])


def test_fingerprint_seed_and_hash_are_stable():
    first = build_fingerprint_identity(seed="42")
    second = build_fingerprint_identity(seed="42")

    assert first.seed == second.seed == "42"
    assert first.revision == second.revision == 1
    assert first.config_hash == second.config_hash


def test_different_seeds_have_different_config_hashes():
    assert build_fingerprint_identity(seed="1").config_hash != build_fingerprint_identity(
        seed="2"
    ).config_hash


def test_operational_behavior_does_not_change_fingerprint_hash():
    first = build_fingerprint_identity(
        seed="42", behavior=BehaviorSettings(clear_cache_before_launch=False)
    )
    second = build_fingerprint_identity(
        seed="42", behavior=BehaviorSettings(clear_cache_before_launch=True)
    )

    assert first.config_hash == second.config_hash


def test_hardware_override_changes_fingerprint_hash():
    automatic = build_fingerprint_identity(seed="42", behavior=BehaviorSettings())
    custom = build_fingerprint_identity(
        seed="42",
        behavior=BehaviorSettings(
            hardware_concurrency_mode="custom", hardware_concurrency=8
        ),
    )

    assert automatic.config_hash != custom.config_hash


def test_profile_defaults_are_safe_and_consistent():
    profile = ProfileCreate(name="  Account A  ")

    assert profile.name == "Account A"
    assert profile.fingerprint_preset == "consistent"
    assert profile.browser_version_mode == "installed"
    assert profile.user_agent_mode == "automatic"
    assert profile.window.mode == "maximized"
    assert profile.behavior.ignore_https_errors is False
    assert profile.startup_urls == []


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
