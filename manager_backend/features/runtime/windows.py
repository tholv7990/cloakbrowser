"""Window arrangement for the Synchronize page (Windows, best-effort).

Pure layout math + an orchestrator with injected Win32 dependencies, plus the
real Win32 WindowManager. Every OS call is guarded and swallowing — arranging
windows must never raise into a request. See
docs/superpowers/specs/2026-07-24-synchronize-window-tiling-design.md.
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass
from typing import Protocol


Rect = tuple[int, int, int, int]       # x, y, w, h  (absolute virtual-desktop px)
WorkArea = tuple[int, int, int, int]   # x, y, w, h

_CASCADE_STEP = 32


def compute_layout(n: int, work_area: WorkArea, layout: str) -> list[Rect]:
    """Absolute (x, y, w, h) rects for `n` windows on `work_area`.

    grid: ceil(sqrt(n)) columns; the right/bottom cells extend to the work-area
    edge so integer division leaves no gap. cascade: fixed-size windows stepped
    by 32px, wrapping before they leave the work area."""
    if n <= 0:
        return []
    wx, wy, width, height = work_area
    if layout == "cascade":
        cw = max(1, round(width * 0.6))
        ch = max(1, round(height * 0.7))
        slots = max(1, min((width - cw) // _CASCADE_STEP, (height - ch) // _CASCADE_STEP))
        return [
            (wx + (i % slots) * _CASCADE_STEP, wy + (i % slots) * _CASCADE_STEP, cw, ch)
            for i in range(n)
        ]
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    cell_w = width // cols
    cell_h = height // rows
    rects: list[Rect] = []
    for i in range(n):
        col, row = i % cols, i // cols
        x, y = wx + col * cell_w, wy + row * cell_h
        w = (width - col * cell_w) if col == cols - 1 else cell_w
        h = (height - row * cell_h) if row == rows - 1 else cell_h
        rects.append((x, y, w, h))
    return rects
