"""Phase B — input sync: mirror one control profile's browser input to followers.

Interact with the "control" profile's window and the same clicks / keystrokes /
scroll / navigation replay in every "follower" window, over each profile's loopback
CDP endpoint (see launcher.read_cdp_endpoint).

Capture runs in a CDP **isolated world** that buffers events, which the service
drains on a short poll. Spiked 2026-07-25 against the stealth binary: the page can
see neither the buffer nor the drain hook (both are `undefined` in the main world),
and no `Runtime.enable` is needed — the alternative, `Runtime.addBinding`, exposes a
callable global to the page in the main world and does not reach an isolated world
without enabling the Runtime domain, itself a known CDP-detection signal. Replay uses
Input.* dispatch + Page.navigate.

One session at a time, on the app's asyncio loop. Workers use sync Playwright on
their own threads; this uses async Playwright on the FastAPI loop — separate instances.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

_WORLD = "__plasma_sync"

# Runs in the isolated world: buffers the input events we mirror and hands them over
# on drain. Nothing here is reachable from the page's own world.
_CAPTURE_JS = """
(() => {
  if (window.__q) return 'already';
  const q = [];
  window.__q = q;
  const s = (o) => { if (q.length < 500) q.push(o); };  // bounded: never grow unboundedly
  const m = (t) => (e) => s({kind:'mouse',type:t,x:e.clientX,y:e.clientY,button:e.button});
  addEventListener('pointerdown', m('mousePressed'), true);
  addEventListener('pointerup', m('mouseReleased'), true);
  const k = (t) => (e) => s({kind:'key',type:t,key:e.key,code:e.code,keyCode:e.keyCode,text:(t==='keyDown'&&e.key.length===1?e.key:'')});
  addEventListener('keydown', k('keyDown'), true);
  addEventListener('keyup', k('keyUp'), true);
  addEventListener('wheel', (e) => s({kind:'wheel',x:e.clientX,y:e.clientY,dx:e.deltaX,dy:e.deltaY}), true);
  window.__drain = () => JSON.stringify(q.splice(0, q.length));
  return 'installed';
})()
"""

_BUTTONS = {0: "left", 1: "middle", 2: "right"}


def translate_event(event: dict) -> list[tuple[str, dict]]:
    """Pure map: a captured control-page input event -> the CDP command(s) that replay
    it on a follower. Unknown / malformed events yield no commands (never raises).

    Coordinates are viewport-relative, so replay lands correctly when the follower
    window is the same size as the control (tile first).
    """
    kind = event.get("kind")
    if kind == "mouse":
        etype = event.get("type")
        if etype not in ("mousePressed", "mouseReleased"):
            return []
        return [(
            "Input.dispatchMouseEvent",
            {
                "type": etype,
                "x": float(event.get("x", 0)),
                "y": float(event.get("y", 0)),
                "button": _BUTTONS.get(event.get("button", 0), "left"),
                "clickCount": 1,
            },
        )]
    if kind == "key":
        etype = event.get("type")
        if etype not in ("keyDown", "keyUp"):
            return []
        params: dict[str, Any] = {
            "type": etype,
            "key": event.get("key", ""),
            "code": event.get("code", ""),
            "windowsVirtualKeyCode": int(event.get("keyCode") or 0),
        }
        text = event.get("text")
        if text:  # printable char: makes the keystroke actually type
            params["text"] = text
        return [("Input.dispatchKeyEvent", params)]
    if kind == "wheel":
        return [(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseWheel",
                "x": float(event.get("x", 0)),
                "y": float(event.get("y", 0)),
                "deltaX": float(event.get("dx", 0)),
                "deltaY": float(event.get("dy", 0)),
            },
        )]
    return []


def _first_page(browser: Any) -> Any | None:
    for ctx in browser.contexts:
        if ctx.pages:
            return ctx.pages[0]
    return None


class InputSyncService:
    """Mirrors input from a control profile to followers over CDP. One session at a
    time; hung on app.state so routes can start/stop/query it."""

    # Drain cadence. 50ms keeps mirrored input imperceptible while costing ~20 cheap
    # CDP evaluates/sec on one page.
    _POLL_SECONDS = 0.05

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop: asyncio.Event | None = None
        self.control_profile_id: str | None = None
        self.follower_profile_ids: list[str] = []

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict:
        return {
            "active": self.active,
            "control_profile_id": self.control_profile_id if self.active else None,
            "follower_profile_ids": list(self.follower_profile_ids) if self.active else [],
        }

    async def start(
        self,
        *,
        control_profile_id: str,
        control_endpoint: str,
        followers: list[tuple[str, str]],
    ) -> None:
        """Begin mirroring. `followers` is [(profile_id, cdp_endpoint), ...].
        Awaits until connected so connection failures surface to the caller."""
        if self.active:
            raise RuntimeError("input_sync_already_active")
        self.control_profile_id = control_profile_id
        self.follower_profile_ids = [pid for pid, _ in followers]
        self._stop = asyncio.Event()
        ready: asyncio.Future = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(
            self._run(control_endpoint, [ep for _, ep in followers], ready)
        )
        try:
            await ready
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._task is not None:
            try:
                await self._task
            except Exception:
                pass
        self._task = None
        self._stop = None
        self.control_profile_id = None
        self.follower_profile_ids = []

    async def _arm(self, ccdp: Any) -> int:
        """(Re)create the isolated world on the control's main frame and install the
        capture buffer in it. Returns the world's execution context id."""
        tree = await ccdp.send("Page.getFrameTree")
        world = await ccdp.send(
            "Page.createIsolatedWorld",
            {
                "frameId": tree["frameTree"]["frame"]["id"],
                "worldName": _WORLD,
                # NB: the CDP parameter really is spelled "grantUniveralAccess".
                "grantUniveralAccess": False,
            },
        )
        context_id = world["executionContextId"]
        await ccdp.send(
            "Runtime.evaluate",
            {"expression": _CAPTURE_JS, "contextId": context_id, "returnByValue": True},
        )
        return context_id

    async def _drain(self, ccdp: Any, context_id: int) -> list[dict]:
        result = await ccdp.send(
            "Runtime.evaluate",
            {
                "expression": "window.__drain()",
                "contextId": context_id,
                "returnByValue": True,
            },
        )
        try:
            return json.loads(result.get("result", {}).get("value") or "[]")
        except (ValueError, TypeError):
            return []

    async def _run(self, control_endpoint, follower_endpoints, ready) -> None:
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        conns: list[Any] = []
        try:
            control = await pw.chromium.connect_over_cdp(control_endpoint)
            conns.append(control)
            followers: list[dict] = []
            for endpoint in follower_endpoints:
                browser = await pw.chromium.connect_over_cdp(endpoint)
                conns.append(browser)
                page = _first_page(browser)
                if page is None:
                    continue
                followers.append({"page": page, "cdp": await page.context.new_cdp_session(page)})

            cpage = _first_page(control)
            if cpage is None:
                raise RuntimeError("control_has_no_page")
            ccdp = await cpage.context.new_cdp_session(cpage)
            await ccdp.send("Page.enable")  # required for frameNavigated events

            loop = asyncio.get_running_loop()
            navigated = asyncio.Event()  # set when the control's document changed

            def _on_nav(params: dict) -> None:
                frame = params.get("frame", {})
                if frame.get("parentId"):  # main frame only
                    return
                navigated.set()  # the isolated world died with the old document
                url = frame.get("url") or ""
                if url and not url.startswith(("about:", "chrome:", "devtools:", "data:")):
                    loop.create_task(self._navigate(url, followers))

            ccdp.on("Page.frameNavigated", _on_nav)
            context_id = await self._arm(ccdp)

            if not ready.done():
                ready.set_result(None)

            while True:
                try:  # doubles as the poll tick and the stop signal
                    await asyncio.wait_for(self._stop.wait(), timeout=self._POLL_SECONDS)
                    break
                except asyncio.TimeoutError:
                    pass
                if navigated.is_set():
                    navigated.clear()
                    try:
                        context_id = await self._arm(ccdp)
                    except Exception:
                        continue  # document still settling; retry on the next tick
                try:
                    events = await self._drain(ccdp, context_id)
                except Exception:
                    # Context destroyed under us (navigation raced the drain) —
                    # re-arm on the next tick rather than ending the session.
                    navigated.set()
                    continue
                for event in events:
                    await self._fanout(event, followers)
        except Exception as error:  # noqa: BLE001 — surface to the awaiting caller
            if not ready.done():
                ready.set_exception(error)
        finally:
            for browser in conns:
                try:
                    await browser.close()
                except Exception:
                    pass
            try:
                await pw.stop()
            except Exception:
                pass

    async def _fanout(self, event: dict, followers: list[dict]) -> None:
        for method, params in translate_event(event):
            for follower in followers:
                try:
                    await follower["cdp"].send(method, params)
                except Exception:
                    pass

    async def _navigate(self, url: str, followers: list[dict]) -> None:
        for follower in followers:
            try:
                await follower["page"].goto(url, wait_until="commit", timeout=15000)
            except Exception:
                pass
