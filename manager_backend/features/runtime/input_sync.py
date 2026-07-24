"""Phase B — input sync: mirror one control profile's browser input to followers.

Interact with the "control" profile's window and the same clicks / keystrokes /
scroll / navigation replay in every "follower" window, over each profile's loopback
CDP endpoint (see launcher.read_cdp_endpoint). Feasibility spiked 2026-07-25:
addBinding->bindingCalled captures input WITHOUT Runtime.enable, and Input.* dispatch
+ Page.navigate replay it faithfully on the stealth binary.

One session at a time, on the app's asyncio loop. Workers use sync Playwright on
their own threads; this uses async Playwright on the FastAPI loop — separate instances.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any

# Injected into the control page (capture phase) to report the input events we
# mirror via the addBinding function. The binding name is randomized per session so
# a page can't fingerprint a fixed global. {b} is the binding name.
_CAPTURE_JS = """
(() => {{
  const B = window.{b};
  if (!B || window.{b}_on) return;
  window.{b}_on = true;
  const s = (o) => {{ try {{ B(JSON.stringify(o)); }} catch (e) {{}} }};
  const m = (t) => (e) => s({{kind:'mouse',type:t,x:e.clientX,y:e.clientY,button:e.button}});
  addEventListener('pointerdown', m('mousePressed'), true);
  addEventListener('pointerup', m('mouseReleased'), true);
  const k = (t) => (e) => s({{kind:'key',type:t,key:e.key,code:e.code,keyCode:e.keyCode,text:(e.key.length===1?e.key:'')}});
  addEventListener('keydown', k('keyDown'), true);
  addEventListener('keyup', k('keyUp'), true);
  addEventListener('wheel', (e) => s({{kind:'wheel',x:e.clientX,y:e.clientY,dx:e.deltaX,dy:e.deltaY}}), true);
}})()
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

    async def _run(self, control_endpoint, follower_endpoints, ready) -> None:
        from playwright.async_api import async_playwright

        binding = "__pl" + secrets.token_hex(6)
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
            await ccdp.send("Runtime.addBinding", {"name": binding})

            loop = asyncio.get_running_loop()

            def _on_binding(params: dict) -> None:
                if params.get("name") == binding:
                    loop.create_task(self._fanout(params.get("payload", ""), followers))

            ccdp.on("Runtime.bindingCalled", _on_binding)

            def _on_nav(params: dict) -> None:
                frame = params.get("frame", {})
                if frame.get("parentId"):  # main frame only
                    return
                url = frame.get("url") or ""
                if url and not url.startswith(("about:", "chrome:", "devtools:", "data:")):
                    loop.create_task(self._navigate(url, followers))

            ccdp.on("Page.frameNavigated", _on_nav)
            await ccdp.send("Page.enable")  # required for frameNavigated events

            capture_js = _CAPTURE_JS.format(b=binding)
            await cpage.add_init_script(capture_js)  # re-arm capture on each navigation
            await cpage.evaluate(capture_js)  # arm the current page

            if not ready.done():
                ready.set_result(None)
            await self._stop.wait()
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

    async def _fanout(self, payload: str, followers: list[dict]) -> None:
        try:
            event = json.loads(payload)
        except (ValueError, TypeError):
            return
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
