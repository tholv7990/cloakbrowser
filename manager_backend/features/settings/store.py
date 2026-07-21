from __future__ import annotations

import json
import os
from pathlib import Path

from .schemas import ManagerPreferences, SettingsPatch


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> ManagerPreferences:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return ManagerPreferences()
        return ManagerPreferences.model_validate(raw)

    def patch(self, patch: SettingsPatch) -> ManagerPreferences:
        current = self.load()
        changes = patch.model_dump(exclude_none=True)
        updated = ManagerPreferences.model_validate({**current.model_dump(), **changes})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(updated.model_dump(), indent=2) + "\n", encoding="utf-8"
        )
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        return updated
