import json

import pytest
from pydantic import ValidationError

from manager_backend.features.settings.schemas import SettingsPatch
from manager_backend.features.settings.store import SettingsStore


def test_settings_store_loads_defaults_when_file_is_absent(tmp_path):
    values = SettingsStore(tmp_path / "settings.json").load()
    assert values.default_locale == "en-US"
    assert values.rows_per_page == 25


def test_settings_store_patch_persists_validated_preferences(tmp_path):
    path = tmp_path / "settings.json"
    SettingsStore(path).patch(SettingsPatch(theme="dark", rows_per_page=50))
    values = SettingsStore(path).load()
    assert values.theme == "dark"
    assert values.rows_per_page == 50
    assert json.loads(path.read_text(encoding="utf-8"))["theme"] == "dark"
    assert not path.with_suffix(".tmp").exists()


def test_settings_patch_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        SettingsPatch.model_validate({"license_key": "secret"})
