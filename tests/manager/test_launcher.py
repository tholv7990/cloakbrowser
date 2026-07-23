from __future__ import annotations

import json

from manager_backend.features.runtime import launcher
from manager_backend.features.runtime.launcher import (
    _read_last_session,
    ensure_initial_preferences,
    persistent_context_kwargs,
    seed_default_search_engine,
    urls_to_open,
)


def test_read_last_session_bounds_count_and_validates_schemes(tmp_path):
    urls = [f"https://ok.example/{i}" for i in range(60)]
    urls += [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "chrome://settings/",
        "data:text/html,x",
        "ftp://host/file",
        "",
        123,
        None,
        "https://" + "a" * 5000,  # over length cap
    ]
    (tmp_path / "last-session.json").write_text(
        json.dumps({"urls": urls}), encoding="utf-8"
    )
    result = _read_last_session(tmp_path)
    assert len(result) <= 25  # small max tabs
    assert all(isinstance(u, str) and u.startswith(("http://", "https://")) for u in result)
    assert all(len(u) <= 2048 for u in result)
    assert "javascript:alert(1)" not in result and "file:///etc/passwd" not in result


class _FakeProc:
    def __init__(self, pid, udd, created=1000.0):
        self.pid = pid
        self.info = {"name": "chrome.exe"}
        self._udd = udd
        self._created = created

    def cmdline(self):
        return ["chrome.exe", f"--user-data-dir={self._udd}", "about:blank"]

    def create_time(self):
        return self._created


def test_locate_browser_requires_exact_user_data_dir_not_substring(tmp_path, monkeypatch):
    owned = str(tmp_path / "prof1" / "user-data")
    # Another chrome whose udd merely CONTAINS ours as a prefix must not match.
    other = str(tmp_path / "prof1" / "user-data-backup")
    monkeypatch.setattr(
        launcher.psutil, "process_iter", lambda attrs=None: [_FakeProc(111, other)]
    )
    handle = launcher._PersistentContextHandle(_FakeContext([]), owned)
    assert handle.browser_pid is None  # did not false-match the "-backup" profile


def test_is_closed_detects_pid_reuse_via_create_time(tmp_path, monkeypatch):
    owned = str(tmp_path / "prof2" / "user-data")
    monkeypatch.setattr(
        launcher.psutil, "process_iter", lambda attrs=None: [_FakeProc(222, owned, created=1000.0)]
    )
    handle = launcher._PersistentContextHandle(_FakeContext([]), owned)
    assert handle.browser_pid == 222  # located exactly

    # The browser is gone, but its pid is reused by an unrelated process.
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs=None: [])
    monkeypatch.setattr(launcher.psutil, "pid_exists", lambda pid: True)

    class _Reused:
        def create_time(self):
            return 9999.0  # different -> not our original process

    monkeypatch.setattr(launcher.psutil, "Process", lambda pid: _Reused())
    handle._last_probe = -1e9
    assert handle.is_closed() is True  # not fooled by the reused pid


def test_read_last_session_rejects_malformed_files(tmp_path):
    session = tmp_path / "last-session.json"
    session.write_text(json.dumps(["raw", "list"]), encoding="utf-8")  # not a dict
    assert _read_last_session(tmp_path) == []
    session.write_text(json.dumps({"urls": "not-a-list"}), encoding="utf-8")
    assert _read_last_session(tmp_path) == []


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


def _write_web_data_with_google(path, active):
    import sqlite3

    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE keywords (keyword TEXT, is_active INTEGER)")
    conn.execute("INSERT INTO keywords VALUES ('google.com', ?)", (1 if active else 0,))
    conn.commit()
    conn.close()


def test_google_search_ready_guard(tmp_path):
    default = tmp_path / "Default"
    default.mkdir()
    # Nothing seeded yet -> not ready.
    assert launcher._google_search_ready(default) is False

    # A DSE in Secure Preferences but no active Google keyword -> still not ready.
    (default / "Secure Preferences").write_text(
        json.dumps({"default_search_provider_data": {"template_url_data": {"short_name": "Google"}}}),
        encoding="utf-8",
    )
    _write_web_data_with_google(default / "Web Data", active=False)
    assert launcher._google_search_ready(default) is False

    # DSE + an ACTIVE Google keyword -> ready (seed is skipped).
    (default / "Web Data").unlink()
    _write_web_data_with_google(default / "Web Data", active=True)
    assert launcher._google_search_ready(default) is True


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
    # Skip the real psutil scan; tests drive liveness by overriding _process_alive.
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

    handle._process_alive = lambda: True
    assert handle.is_closed() is False  # alive -> snapshots the live tabs
    saved = json.loads((tmp_path / "last-session.json").read_text())
    assert saved["urls"] == ["https://a.example/", "https://b.example/"]

    # User closes the window directly: the process is gone.
    handle._process_alive = lambda: False
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
    handle._process_alive = lambda: True
    handle.is_closed()
    saved = json.loads((tmp_path / "last-session.json").read_text())
    assert saved["urls"] == ["https://keep.example/"]


def _search(prefs):
    return prefs.get("default_search_provider_data", {}).get("template_url_data", {}).get(
        "short_name"
    )


def test_seed_default_search_engine_heals_existing_profiles(tmp_path):
    udd = tmp_path / "user-data"
    default = udd / "Default"
    default.mkdir(parents=True)
    prefs = default / "Preferences"
    secure = default / "Secure Preferences"

    # Brand-new profile (no Preferences yet) -> left to initial_preferences.
    seed_default_search_engine(udd)
    assert not prefs.exists()

    # Existing profile with prefs but no provider -> healed: provider seeded and
    # Secure Preferences dropped so Chromium re-baselines its tracked-pref MACs
    # (otherwise the seeded value is reset as tampering).
    prefs.write_text(json.dumps({"some_key": 1}), encoding="utf-8")
    secure.write_text(json.dumps({"protection": {"macs": {}}}), encoding="utf-8")
    seed_default_search_engine(udd)
    restored = json.loads(prefs.read_text(encoding="utf-8"))
    assert restored["some_key"] == 1  # other prefs preserved
    assert _search(restored) == "Google"
    assert not secure.exists()

    # A provider already present (healed, or user-chosen) is never overwritten,
    # and Secure Preferences is left untouched (one-time heal).
    prefs.write_text(
        json.dumps({"default_search_provider_data": {"template_url_data": {"short_name": "Bing"}}}),
        encoding="utf-8",
    )
    secure.write_text(json.dumps({"protection": {"macs": {}}}), encoding="utf-8")
    seed_default_search_engine(udd)
    assert _search(json.loads(prefs.read_text(encoding="utf-8"))) == "Bing"
    assert secure.exists()


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


def test_webrtc_ip_spoofed_to_proxy_only_in_proxy_mode_with_a_proxy():
    # webrtc_mode="proxy" + a proxy -> spoof the WebRTC IP to the exit IP so the
    # real IP can't leak via STUN.
    proxied = persistent_context_kwargs(
        {
            "fingerprint_seed": 8200,
            "fingerprint_preset": "consistent",
            "proxy_url": "socks5://user:pass@1.2.3.4:1080",
            "location": {"webrtc_mode": "proxy"},
        },
        headless=True,
    )
    assert "--fingerprint-webrtc-ip=auto" in proxied["args"]

    # "direct" is an explicit opt-in to the real path -> no spoof flag.
    direct = persistent_context_kwargs(
        {
            "fingerprint_seed": 8200,
            "fingerprint_preset": "consistent",
            "proxy_url": "socks5://1.2.3.4:1080",
            "location": {"webrtc_mode": "direct"},
        },
        headless=True,
    )
    assert not any(a.startswith("--fingerprint-webrtc-ip") for a in direct["args"])

    # No proxy -> nothing to spoof to, so no flag even in proxy mode.
    no_proxy = persistent_context_kwargs(
        {
            "fingerprint_seed": 8200,
            "fingerprint_preset": "consistent",
            "location": {"webrtc_mode": "proxy"},
        },
        headless=True,
    )
    assert not any(a.startswith("--fingerprint-webrtc-ip") for a in no_proxy["args"])
