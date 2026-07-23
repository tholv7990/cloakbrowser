from __future__ import annotations

from manager_backend.features.runtime import window_icon


def test_color_for_is_stable_and_distinct():
    a = window_icon._color_for("profile-A")
    assert window_icon._color_for("profile-A") == a  # stable per profile
    assert window_icon._color_for("profile-B") != a  # distinct per profile
    assert all(0 <= c <= 255 for c in a)


def test_ensure_ico_creates_a_multisize_icon(tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.setattr(window_icon, "_ICON_DIR", tmp_path)
    path = window_icon._ensure_ico((90, 200, 255))
    assert path.exists() and path.stat().st_size > 0
    with Image.open(path) as image:
        assert image.format == "ICO"
    # cached: same colour returns the same file without regenerating
    assert window_icon._ensure_ico((90, 200, 255)) == path


def test_apply_is_a_safe_noop_off_windows_or_without_processes(tmp_path, monkeypatch):
    # No chrome processes on this dir -> zero windows, no raise.
    monkeypatch.setattr(window_icon, "_profile_chrome_pids", lambda udd: set())
    assert window_icon.apply_profile_window_icon(str(tmp_path), "seed") == 0
