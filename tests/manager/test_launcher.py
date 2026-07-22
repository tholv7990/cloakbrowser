from __future__ import annotations

import json

from manager_backend.features.runtime import launcher
from manager_backend.features.runtime.launcher import (
    ensure_initial_preferences,
    persistent_context_kwargs,
    seed_default_search_engine,
    urls_to_open,
)


def test_ensure_initial_preferences_seeds_google_search(tmp_path):
    # The default search provider is a protected pref; the only way to seed it is
    # the binary's initial_preferences, applied on a profile's first run.
    ensure_initial_preferences(tmp_path)
    data = json.loads((tmp_path / "initial_preferences").read_text(encoding="utf-8"))
    template = data["default_search_provider_data"]["template_url_data"]
    assert template["short_name"] == "Google"
    assert "{searchTerms}" in template["url"]
    assert data["distribution"]["skip_first_run_ui"] is True

    # Idempotent: an unchanged file is left as-is (no needless rewrite).
    marker = tmp_path / "initial_preferences"
    stamp = marker.stat().st_mtime_ns
    ensure_initial_preferences(tmp_path)
    assert marker.stat().st_mtime_ns == stamp


def test_ensure_initial_preferences_never_raises_on_bad_dir(tmp_path):
    missing = tmp_path / "does-not-exist"
    ensure_initial_preferences(missing)  # parent absent -> swallowed, no crash


class _FakeCDPSession:
    def __init__(self, infos):
        self._infos = infos
        self.detached = False

    def send(self, method, params=None):
        assert method == "Target.getTargets"
        return {"targetInfos": self._infos}

    def detach(self):
        self.detached = True


class _FakeContext:
    """Minimal stand-in for a Playwright persistent context.

    Exposes `Target.getTargets` via a CDP session — the live source of truth for
    open tabs that the handle snapshots — plus a non-empty `pages` list to bind to.
    """

    def __init__(self, target_urls, *, extra_infos=None):
        self.target_infos = [{"type": "page", "url": u} for u in target_urls]
        if extra_infos:
            self.target_infos += list(extra_infos)
        self.pages = [object()]
        self.closed = False

    def on(self, event, callback):
        pass

    def new_cdp_session(self, page):
        return _FakeCDPSession(self.target_infos)

    def close(self):
        self.closed = True


def _handle(monkeypatch, context, udd):
    # Skip the real psutil process scan; we drive liveness via pid_exists below.
    monkeypatch.setattr(
        launcher._PersistentContextHandle, "_locate_browser", lambda self: False
    )
    handle = launcher._PersistentContextHandle(context, str(udd))
    handle.browser_pid = 4242
    handle._last_probe = -1e9  # force the throttled probe to run
    return handle


def test_direct_window_close_still_restores_tabs(tmp_path, monkeypatch):
    # Reproduces the bug: user closes the window with the X (never the manager's
    # Stop), so close() no-ops — yet the tabs must survive because a periodic
    # snapshot captured them while the browser was alive.
    udd = tmp_path / "user-data"
    udd.mkdir(parents=True)
    context = _FakeContext(
        ["https://a.example/", "https://b.example/"],
        extra_infos=[{"type": "page", "url": "chrome://newtab/"}],  # internal, filtered
    )
    handle = _handle(monkeypatch, context, udd)

    monkeypatch.setattr(launcher.psutil, "pid_exists", lambda pid: True)
    assert handle.is_closed() is False  # alive -> snapshots the live tabs
    saved = json.loads((tmp_path / "last-session.json").read_text())
    assert saved["urls"] == ["https://a.example/", "https://b.example/"]

    # User closes the window directly: the process is gone.
    monkeypatch.setattr(launcher.psutil, "pid_exists", lambda pid: False)
    handle._last_probe = -1e9
    assert handle.is_closed() is True
    handle.close()  # no-op (already closed), must not wipe the snapshot
    saved = json.loads((tmp_path / "last-session.json").read_text())
    assert saved["urls"] == ["https://a.example/", "https://b.example/"]


def test_snapshot_never_wipes_session_with_empty(tmp_path, monkeypatch):
    # A snapshot that sees only internal tabs must never overwrite a good session
    # (guards a close-race from blanking the restore list).
    udd = tmp_path / "user-data"
    udd.mkdir(parents=True)
    (tmp_path / "last-session.json").write_text(
        json.dumps({"urls": ["https://keep.example/"]}), encoding="utf-8"
    )
    context = _FakeContext([], extra_infos=[{"type": "page", "url": "chrome://newtab/"}])
    handle = _handle(monkeypatch, context, udd)
    monkeypatch.setattr(launcher.psutil, "pid_exists", lambda pid: True)
    handle.is_closed()
    saved = json.loads((tmp_path / "last-session.json").read_text())
    assert saved["urls"] == ["https://keep.example/"]


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
