"""One-time seed that makes a profile's omnibox actually search Google.

The stealth binary ships every search engine DISABLED (`is_active=0`) with a
built-in "No Search" default, and Google is not prepopulated — so typing a word
navigates to it as a hostname (`tes` -> http://tes/). Making the omnibox search
requires three things, all verified end-to-end against the real binary:

  1. A custom Google default search provider (prepopulate_id 0) seeded via the
     binary's `initial_preferences`, stamped with a valid tracked-pref MAC by a
     REAL first-run launch — Playwright launches with `--no-first-run`, which
     skips this, and a plain-`Preferences` write is ignored as an untrusted
     protected pref.
  2. That first-run launch closed gracefully so Chromium flushes `Secure
     Preferences` (a hard kill skips the flush -> no MAC).
  3. An ACTIVE Google row inserted into the `keywords` Web Data table (every
     shipped engine is `is_active=0`, and Chromium won't add the custom DSE there
     on its own).

Run as: ``python -m manager_backend.features.runtime.google_seed <user-data-dir>``
so it is isolated from the manager's own Playwright driver. Best-effort; a failure
here must never block a profile launch.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


_GUID = "g00g1e00-0000-4000-a000-000000000001"
_GOOGLE_TEMPLATE = {
    "short_name": "Google",
    "keyword": "google.com",
    "url": "https://www.google.com/search?q={searchTerms}",
    "suggestions_url": "https://www.google.com/complete/search?output=chrome&q={searchTerms}",
    "favicon_url": "https://www.google.com/favicon.ico",
    "safe_for_autoreplace": False,
    "input_encodings": ["UTF-8"],
    "date_created": "0",
    "last_modified": "0",
    "id": "1001",
    "sync_guid": _GUID,
    "prepopulate_id": 0,  # custom engine — a real prepopulate_id the binary lacks is ignored
    "is_active": 1,
}
_INITIAL_PREFERENCES = {
    "distribution": {"skip_first_run_ui": True, "import_search_engine": False,
                     "import_history": False, "make_chrome_default": False},
    "default_search_provider_data": {"template_url_data": _GOOGLE_TEMPLATE},
}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _graceful_close(port: int, proc: subprocess.Popen) -> None:
    """Close via CDP so Chromium flushes Secure Preferences (the stamped MAC)."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}").close()
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=15)
    except Exception:
        proc.kill()
    time.sleep(1)


def _insert_active_google_keyword(web_data: Path) -> None:
    if not web_data.exists():
        return
    conn = sqlite3.connect(str(web_data))
    try:
        if conn.execute(
            "SELECT 1 FROM keywords WHERE keyword='google.com' AND is_active=1"
        ).fetchone():
            return
        conn.execute(
            "INSERT INTO keywords (short_name,keyword,favicon_url,url,safe_for_autoreplace,"
            "originating_url,date_created,usage_count,input_encodings,suggest_url,prepopulate_id,"
            "created_by_policy,last_modified,sync_guid,alternate_urls,image_url,"
            "search_url_post_params,suggest_url_post_params,image_url_post_params,new_tab_url,"
            "is_active,starter_pack_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "Google", "google.com", "https://www.google.com/favicon.ico",
                "https://www.google.com/search?q={searchTerms}", 0, "", 0, 0, "UTF-8",
                "https://www.google.com/complete/search?output=chrome&q={searchTerms}",
                0, 0, 0, _GUID, "", "", "", "", "", "", 1, 0,
            ),
        )
        conn.commit()
    except sqlite3.Error:
        pass
    finally:
        conn.close()


def seed(user_data_dir: str) -> None:
    from cloakbrowser.config import get_binary_dir, get_binary_path

    udd = Path(user_data_dir)
    default = udd / "Default"
    chrome = str(get_binary_path(None))
    binary_dir = Path(get_binary_dir(None))

    (binary_dir / "initial_preferences").write_text(
        json.dumps(_INITIAL_PREFERENCES), encoding="utf-8"
    )
    # Drop the tracked-pref store so the first-run launch re-stamps the DSE MAC
    # (works for both brand-new and already-run profiles).
    try:
        (default / "Secure Preferences").unlink(missing_ok=True)
    except OSError:
        pass

    port = _free_port()
    proc = subprocess.Popen(
        [chrome, f"--user-data-dir={udd}", "--no-sandbox", "--no-default-browser-check",
         f"--remote-debugging-port={port}", "--window-position=-32000,-32000",
         "--window-size=1,1", "about:blank"]
    )
    time.sleep(6)
    _graceful_close(port, proc)
    _insert_active_google_keyword(default / "Web Data")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        try:
            seed(sys.argv[1])
        except Exception:
            pass  # best-effort; never fail a launch over search seeding
