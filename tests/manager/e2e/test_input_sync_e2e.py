"""Browser-to-browser proof for input sync (Phase B).

Launches two real profiles the way the manager does, runs the shipped
InputSyncService against them, and asserts a user's navigation, clicks and
keystrokes in the control window actually reach the follower — including in a
second tab. The unit tests cover the event->CDP translation and the routes; only
this one proves the mirror itself, so a change that silently breaks it fails here.

Notes learned the hard way (see docs/superpowers/specs/2026-07-25-phase-b-input-sync-design.md):
  * Focus propagates only through mirrored *user input* — click the field, never
    page.focus(), which is a driver call and mirrors nothing.
  * The nav mirror ignores data:/about:/chrome: URLs, so the fixture serves real http.
"""

from __future__ import annotations

import asyncio
import http.server
import os
import tempfile
import threading
from pathlib import Path

import pytest

from manager_backend.features.runtime.input_sync import InputSyncService
from manager_backend.features.runtime.launcher import read_cdp_endpoint


pytestmark = [
    pytest.mark.manager_e2e,
    pytest.mark.skipif(os.name != "nt", reason="Windows Manager E2E only"),
]

_HTML = (
    "<body style='margin:0'>"
    "<input id='t' style='width:400px;height:40px;font-size:20px'>"
    "<button id='b' style='position:absolute;left:100px;top:120px;width:200px;height:80px' "
    "onclick='window.__c=(window.__c||0)+1'>CLICK</button>"
    "</body>"
)


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler API
        body = _HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):  # keep the test output clean
        pass


@pytest.fixture
def page_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()


@pytest.fixture
def two_profiles():
    """Two headed profiles, each launched on its own thread (sync Playwright is
    thread-affine — the same reason every ProfileWorker owns its context)."""
    import cloakbrowser

    stop = threading.Event()
    endpoints: dict[str, str | None] = {}
    threads: list[threading.Thread] = []

    def launch(tag: str) -> None:
        ready = threading.Event()

        def run() -> None:
            udd = Path(tempfile.mkdtemp(prefix=f"syncE2E-{tag}-"))
            context = cloakbrowser.launch_persistent_context(
                str(udd),
                headless=False,
                args=["--remote-debugging-port=0", "--window-size=900,700"],
            )
            endpoints[tag] = read_cdp_endpoint(str(udd), timeout=20)
            ready.set()
            stop.wait()
            try:
                context.close()
            except Exception:
                pass

        thread = threading.Thread(target=run, name=f"syncE2E-{tag}", daemon=True)
        thread.start()
        threads.append(thread)
        assert ready.wait(180), f"{tag} profile did not launch"

    launch("control")
    launch("follower")
    try:
        assert endpoints.get("control") and endpoints.get("follower"), (
            f"no CDP endpoint: {endpoints}"
        )
        yield endpoints["control"], endpoints["follower"]
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=30)


async def _until(predicate, timeout: float = 15.0, interval: float = 0.25):
    """Poll an async predicate until it returns truthy (mirroring is asynchronous)."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(interval)
    return False


async def _click(cdp, page, selector: str) -> None:
    """A real mirrored click — the only way focus reaches the follower."""
    box = await page.evaluate(
        "(s)=>{const r=document.querySelector(s).getBoundingClientRect();"
        "return {x:r.x+r.width/2,y:r.y+r.height/2}}",
        selector,
    )
    for event_type in ("mousePressed", "mouseReleased"):
        await cdp.send(
            "Input.dispatchMouseEvent",
            {"type": event_type, "x": box["x"], "y": box["y"],
             "button": "left", "clickCount": 1},
        )


async def _type(cdp, text: str) -> None:
    for char in text:
        code = f"Key{char.upper()}"
        await cdp.send("Input.dispatchKeyEvent",
                       {"type": "keyDown", "text": char, "key": char,
                        "code": code, "windowsVirtualKeyCode": ord(char.upper())})
        await cdp.send("Input.dispatchKeyEvent",
                       {"type": "keyUp", "key": char, "code": code,
                        "windowsVirtualKeyCode": ord(char.upper())})
        await asyncio.sleep(0.02)


async def test_control_window_mirrors_navigation_clicks_and_typing(two_profiles, page_url):
    from playwright.async_api import async_playwright

    control_endpoint, follower_endpoint = two_profiles
    service = InputSyncService()
    await service.start(
        control_profile_id="control",
        control_endpoint=control_endpoint,
        followers=[("follower", follower_endpoint)],
    )
    assert service.status()["active"] is True

    try:
        async with async_playwright() as pw:
            # Separate connections: the "user" driving the control, and an observer
            # on the follower. The service holds its own.
            control = await pw.chromium.connect_over_cdp(control_endpoint)
            follower = await pw.chromium.connect_over_cdp(follower_endpoint)
            cctx, fctx = control.contexts[0], follower.contexts[0]
            cpage, fpage = cctx.pages[0], fctx.pages[0]

            # 1. Navigation mirrors.
            await cpage.goto(page_url, wait_until="domcontentloaded")
            assert await _until(lambda: _resolved(fpage.url.startswith("http://127.0.0.1"))), (
                f"follower did not follow navigation (at {fpage.url})"
            )
            await fpage.wait_for_selector("#b", timeout=15000)

            ccdp = await cpage.context.new_cdp_session(cpage)

            # 2. Clicks mirror.
            await _click(ccdp, cpage, "#b")
            assert await _until(lambda: _truthy(fpage.evaluate("window.__c||0"))), (
                "click did not mirror to the follower"
            )

            # 3. Typing mirrors — focus arrives via the mirrored click above.
            await _click(ccdp, cpage, "#t")
            assert await _until(
                lambda: _equals(fpage.evaluate("document.activeElement&&document.activeElement.id"), "t")
            ), "the mirrored click did not focus the follower's field"
            await _type(ccdp, "HELLO")
            assert await _until(
                lambda: _equals(fpage.evaluate("document.getElementById('t').value"), "HELLO")
            ), "typing did not mirror to the follower"

            # 4. A second tab mirrors: the follower opens one and mirrors into it.
            cpage2 = await cctx.new_page()
            assert await _until(lambda: _resolved(len(_open(fctx)) >= 2), timeout=20), (
                "follower did not open a matching second tab"
            )
            await cpage2.goto(page_url, wait_until="domcontentloaded")
            fpage2 = _open(fctx)[1]
            assert await _until(
                lambda: _resolved(fpage2.url.startswith("http://127.0.0.1")), timeout=20
            ), f"second tab did not follow navigation (at {fpage2.url})"

            await fpage2.wait_for_selector("#b", timeout=15000)
            ccdp2 = await cpage2.context.new_cdp_session(cpage2)
            await _click(ccdp2, cpage2, "#b")
            assert await _until(lambda: _truthy(fpage2.evaluate("window.__c||0"))), (
                "click in the second tab did not mirror"
            )
            # The first tab must not have received the second tab's click.
            assert await fpage.evaluate("window.__c||0") == 1

            await control.close()
            await follower.close()
    finally:
        await service.stop()

    assert service.status()["active"] is False


def _open(context):
    return [page for page in context.pages if not page.is_closed()]


async def _resolved(value):
    return value


async def _truthy(awaitable):
    return bool(await awaitable)


async def _equals(awaitable, expected):
    return (await awaitable) == expected
