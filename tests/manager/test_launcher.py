from __future__ import annotations

import json

from manager_backend.features.runtime.launcher import (
    persistent_context_kwargs,
    seed_default_search_engine,
    urls_to_open,
)


def _search(prefs):
    return prefs.get("default_search_provider_data", {}).get("template_url_data", {}).get(
        "short_name"
    )


def test_seed_default_search_engine_creates_and_preserves(tmp_path):
    udd = tmp_path / "user-data"
    prefs = udd / "Default" / "Preferences"

    # Fresh profile -> Google is seeded.
    seed_default_search_engine(udd)
    assert _search(json.loads(prefs.read_text(encoding="utf-8"))) == "Google"

    # A search engine the user already chose is never overwritten.
    prefs.write_text(
        json.dumps({"default_search_provider_data": {"template_url_data": {"short_name": "Bing"}}}),
        encoding="utf-8",
    )
    seed_default_search_engine(udd)
    assert _search(json.loads(prefs.read_text(encoding="utf-8"))) == "Bing"

    # An existing profile with other prefs but no search engine gets one added.
    prefs.write_text(json.dumps({"some_key": 1}), encoding="utf-8")
    seed_default_search_engine(udd)
    restored = json.loads(prefs.read_text(encoding="utf-8"))
    assert restored["some_key"] == 1
    assert _search(restored) == "Google"


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


def test_headless_launches_get_no_window_size():
    # Cookie/diagnostic (headless) utility launches must not be window-sized.
    kwargs = persistent_context_kwargs(
        {"fingerprint_seed": 8200, "fingerprint_preset": "consistent"}, headless=True
    )
    assert kwargs["args"] == ["--fingerprint=8200"]


def test_headed_runtime_sizes_window_to_spoofed_screen():
    # Maximized/default -> 1920x1080 (matches the consistent preset's screen), so
    # the window can't leak a larger real monitor.
    maximized = persistent_context_kwargs(
        {"fingerprint_seed": 8200, "fingerprint_preset": "consistent", "window": {"mode": "maximized"}},
        headless=False,
    )
    assert maximized["args"] == ["--fingerprint=8200", "--window-size=1920,1080"]

    # A custom size is honored verbatim.
    custom = persistent_context_kwargs(
        {
            "fingerprint_seed": 8200,
            "fingerprint_preset": "consistent",
            "window": {"mode": "custom", "width": 1366, "height": 768},
        },
        headless=False,
    )
    assert custom["args"] == ["--fingerprint=8200", "--window-size=1366,768"]
