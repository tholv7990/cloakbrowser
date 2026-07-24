from __future__ import annotations

from manager_backend.features.runtime.windows import compute_layout


WORK = (0, 0, 1920, 1040)  # x, y, w, h


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
