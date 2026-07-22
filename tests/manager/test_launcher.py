from __future__ import annotations

import json

from manager_backend.features.runtime.launcher import (
    persistent_context_kwargs,
    urls_to_open,
)


def test_urls_to_open_restores_saved_session_over_startup(tmp_path):
    # No saved session yet -> seed the profile's startup_urls.
    assert urls_to_open(tmp_path, ["https://start.example/"]) == ["https://start.example/"]

    # After a stop saved tabs, reopen those instead (ignoring startup_urls).
    (tmp_path / "last-session.json").write_text(
        json.dumps({"urls": ["https://a.example/", "https://b.example/"]}), encoding="utf-8"
    )
    assert urls_to_open(tmp_path, ["https://start.example/"]) == [
        "https://a.example/",
        "https://b.example/",
    ]


def test_urls_to_open_falls_back_on_corrupt_session(tmp_path):
    (tmp_path / "last-session.json").write_text("{ not json", encoding="utf-8")
    assert urls_to_open(tmp_path, ["https://start.example/"]) == ["https://start.example/"]


def test_persistent_context_kwargs_args_unchanged():
    kwargs = persistent_context_kwargs(
        {"fingerprint_seed": 8200, "fingerprint_preset": "consistent"}, headless=True
    )
    assert kwargs["args"] == ["--fingerprint=8200"]
