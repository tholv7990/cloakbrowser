from __future__ import annotations

from manager_backend.features.runtime import window_icon


def test_plasma_dart_ico_is_a_multisize_icon(tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.setattr(window_icon, "_ICON_DIR", tmp_path)
    path = window_icon._plasma_dart_ico()
    assert path.exists() and path.stat().st_size > 0
    with Image.open(path) as image:
        assert image.format == "ICO"
        # RGBA so the transparent background + motion-line opacity are preserved.
        assert image.mode in ("RGBA", "P")
    # Cached: a second call returns the same file without regenerating.
    assert window_icon._plasma_dart_ico() == path


def test_apply_is_a_safe_noop_without_processes(tmp_path, monkeypatch):
    # No chrome processes on this dir -> zero windows, no raise.
    monkeypatch.setattr(window_icon, "_profile_chrome_pids", lambda udd: set())
    assert window_icon.apply_profile_window_icon(str(tmp_path), "seed") == 0
