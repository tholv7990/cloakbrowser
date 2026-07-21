import pytest

from cloakbrowser.browser import _apply_fingerprint_preset, build_args


def test_consistent_preset_disables_noise():
    args = _apply_fingerprint_preset([], "consistent", persistent=False)
    assert args == ["--fingerprint-noise=false"]


def test_consistent_persistent_preset_adds_storage_quota():
    args = _apply_fingerprint_preset([], "consistent", persistent=True)
    assert args == ["--fingerprint-noise=false", "--fingerprint-storage-quota=10240"]


def test_caller_args_override_consistent_preset_by_flag_key():
    args = _apply_fingerprint_preset(
        ["--fingerprint-noise=true", "--fingerprint-storage-quota=9000"],
        "consistent",
        persistent=True,
    )
    merged = build_args(False, args)
    assert "--fingerprint-noise=true" in merged
    assert "--fingerprint-storage-quota=9000" in merged
    assert "--fingerprint-noise=false" not in merged
    assert "--fingerprint-storage-quota=10240" not in merged


def test_default_preset_adds_nothing():
    assert _apply_fingerprint_preset(["--foo"], "default", persistent=True) == ["--foo"]
    assert _apply_fingerprint_preset([], None, persistent=False) == []


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError, match="fingerprint_preset"):
        _apply_fingerprint_preset([], "pixelscan", persistent=False)
