"""Phase 2: data_root resolves to %LOCALAPPDATA%\\Plasma, but adopts an existing
legacy %LOCALAPPDATA%\\CloakBrowser\\Manager in place so upgrading users' profiles
are never orphaned. PLASMA_DATA_ROOT_MODE forces a choice; CLOAK_MANAGER_DATA_ROOT
overrides everything."""

from __future__ import annotations

import pytest

from manager_backend.config import ManagerSettings, default_data_root


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("CLOAK_MANAGER_DATA_ROOT", raising=False)
    monkeypatch.delenv("PLASMA_DATA_ROOT_MODE", raising=False)
    monkeypatch.delenv("PLASMA_ALLOWED_ORIGIN", raising=False)


def test_allowed_origin_defaults_to_dev_origin(monkeypatch, tmp_path):
    assert ManagerSettings(data_root=tmp_path).allowed_origin == "http://127.0.0.1:5273"


def test_allowed_origin_reads_env(monkeypatch, tmp_path):
    # The desktop shell sets this to the WebView origin (e.g. http://tauri.localhost).
    monkeypatch.setenv("PLASMA_ALLOWED_ORIGIN", "http://tauri.localhost")
    assert ManagerSettings(data_root=tmp_path).allowed_origin == "http://tauri.localhost"


def _base(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def _legacy(base):
    return base / "CloakBrowser" / "Manager"


def test_fresh_install_uses_plasma(monkeypatch, tmp_path):
    base = _base(monkeypatch, tmp_path)
    assert default_data_root() == base / "Plasma"


def test_adopts_legacy_in_place_when_present_and_no_plasma(monkeypatch, tmp_path):
    base = _base(monkeypatch, tmp_path)
    _legacy(base).mkdir(parents=True)
    assert default_data_root() == _legacy(base)


def test_prefers_plasma_when_both_exist(monkeypatch, tmp_path):
    base = _base(monkeypatch, tmp_path)
    (base / "Plasma").mkdir()
    _legacy(base).mkdir(parents=True)
    assert default_data_root() == base / "Plasma"


def test_mode_legacy_forces_legacy(monkeypatch, tmp_path):
    base = _base(monkeypatch, tmp_path)
    (base / "Plasma").mkdir()  # present, but the mode overrides
    monkeypatch.setenv("PLASMA_DATA_ROOT_MODE", "legacy")
    assert default_data_root() == _legacy(base)


def test_mode_plasma_forces_plasma(monkeypatch, tmp_path):
    base = _base(monkeypatch, tmp_path)
    _legacy(base).mkdir(parents=True)  # present, but the mode overrides
    monkeypatch.setenv("PLASMA_DATA_ROOT_MODE", "plasma")
    assert default_data_root() == base / "Plasma"


def test_explicit_override_wins(monkeypatch, tmp_path):
    _base(monkeypatch, tmp_path)
    override = tmp_path / "custom-root"
    monkeypatch.setenv("CLOAK_MANAGER_DATA_ROOT", str(override))
    # Even with legacy present and a mode set, the explicit override is used.
    monkeypatch.setenv("PLASMA_DATA_ROOT_MODE", "legacy")
    assert default_data_root() == override
