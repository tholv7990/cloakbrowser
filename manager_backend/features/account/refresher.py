"""Background entitlement refresher.

A daemon thread that periodically re-fetches the signed entitlement so a
revoked/expired key stops re-issuing and the cached entitlement lapses within a day
(the launch gate then blocks). Sleeps first, so it never fires during a short-lived
process/test; best-effort, so a dead key or offline moment just leaves the current
cached entitlement to age toward its offline-grace deadline.
"""

from __future__ import annotations

import threading


def start_entitlement_refresher(get_service, *, interval_seconds: int, stop_event=None):
    stop = stop_event or threading.Event()

    def loop() -> None:
        while not stop.wait(interval_seconds):
            try:
                get_service().refresh_entitlement()
            except Exception:
                pass  # best effort; the cached entitlement ages out on its own

    threading.Thread(target=loop, name="entitlement-refresher", daemon=True).start()
    return stop
