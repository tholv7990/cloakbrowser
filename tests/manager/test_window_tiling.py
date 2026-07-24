from __future__ import annotations

from manager_backend.features.runtime.windows import (
    Monitor,
    arrange_windows,
    compute_layout,
    safe_profile_id,
)


WORK = (0, 0, 1920, 1040)  # x, y, w, h


class FakeManager:
    def __init__(self, windows: dict[str, int], move_ok: bool = True):
        self._windows = windows          # user_data_dir -> hwnd
        self._move_ok = move_ok
        self.moved: list[tuple[int, tuple]] = []

    def list_monitors(self):
        return [Monitor("0", "Main", 1920, 1080, (0, 0, 1920, 1040), True)]

    def find_main_window(self, user_data_dir: str):
        return self._windows.get(user_data_dir)

    def move_window(self, hwnd: int, rect):
        self.moved.append((hwnd, rect))
        return self._move_ok


def test_grid_single_window_fills_work_area():
    assert compute_layout(1, WORK, "grid") == [(0, 0, 1920, 1040)]


def test_grid_four_windows_two_by_two():
    rects = compute_layout(4, WORK, "grid")
    assert len(rects) == 4
    assert rects[0] == (0, 0, 960, 520)
    assert rects[3] == (960, 520, 960, 520)


def test_grid_three_windows_edges_absorb_remainder():
    # cols=2, rows=2. Odd width/height must be absorbed by the last col/row so
    # windows meet the work-area edge with no dead gap.
    rects = compute_layout(3, (0, 0, 1921, 1041), "grid")
    assert rects[1][0] + rects[1][2] == 1921  # right edge of top-right window
    assert rects[2][1] + rects[2][3] == 1041  # bottom edge of bottom-left window


def test_zero_windows_is_empty():
    assert compute_layout(0, WORK, "grid") == []
    assert compute_layout(0, WORK, "cascade") == []


def test_cascade_steps_and_wraps_on_screen():
    rects = compute_layout(60, WORK, "cascade")
    assert len(rects) == 60
    # Every window stays fully within the work area.
    for x, y, w, h in rects:
        assert 0 <= x and x + w <= 1920
        assert 0 <= y and y + h <= 1040
    # First is at the origin; the second is stepped down-right.
    assert rects[0][0] == 0 and rects[0][1] == 0
    assert rects[1][0] == 32 and rects[1][1] == 32


def test_arrange_positions_running_and_skips_others():
    mgr = FakeManager(windows={"/p/a/ud": 11, "/p/c/ud": 33})
    items = [("a", "/p/a/ud"), ("b", "/p/b/ud"), ("c", "/p/c/ud")]
    results = arrange_windows(items, (0, 0, 1920, 1040), "grid", mgr)
    assert results == [
        {"profile_id": "a", "ok": True, "error": None},
        {"profile_id": "b", "ok": False, "error": "not_running"},
        {"profile_id": "c", "ok": True, "error": None},
    ]
    # Only the two running windows were laid out (n=2), in original order.
    assert [hwnd for hwnd, _ in mgr.moved] == [11, 33]


def test_arrange_reports_position_failure():
    mgr = FakeManager(windows={"/p/a/ud": 11}, move_ok=False)
    results = arrange_windows([("a", "/p/a/ud")], (0, 0, 1920, 1040), "grid", mgr)
    assert results == [{"profile_id": "a", "ok": False, "error": "position_failed"}]


def test_arrange_none_user_data_dir_is_not_running():
    mgr = FakeManager(windows={})
    results = arrange_windows([("x", None)], (0, 0, 1920, 1040), "grid", mgr)
    assert results == [{"profile_id": "x", "ok": False, "error": "not_running"}]


def test_safe_profile_id_rejects_traversal():
    assert safe_profile_id("abc-123")
    assert not safe_profile_id("../etc")
    assert not safe_profile_id("a/b")
    assert not safe_profile_id("..")
    assert not safe_profile_id("")
