from __future__ import annotations

import json
from pathlib import Path


def test_checked_in_openapi_matches_generated_application_contract(client):
    expected = json.dumps(client.app.openapi(), indent=2) + "\n"
    checked_in = Path(__file__).parents[2] / "manager_backend" / "openapi.json"
    assert checked_in.read_text(encoding="utf-8") == expected
