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
  // CDP modifier bitmask: Alt=1, Ctrl=2, Meta=4, Shift=8.
  const mod = (e) => (e.altKey?1:0)|(e.ctrlKey?2:0)|(e.metaKey?4:0)|(e.shiftKey?8:0);
  const m = (t) => (e) => s({kind:'mouse',type:t,x:e.clientX,y:e.clientY,button:e.button,mod:mod(e)});
  addEventListener('pointerdown', m('mousePressed'), true);
  addEventListener('pointerup', m('mouseReleased'), true);
  const k = (t) => (e) => s({kind:'key',type:t,key:e.key,code:e.code,keyCode:e.keyCode,mod:mod(e),text:(t==='keyDown'&&e.key.length===1?e.key:'')});
  addEventListener('keydown', k('keyDown'), true);
  addEventListener('keyup', k('keyUp'), true);
  addEventListener('wheel', (e) => s({kind:'wheel',x:e.clientX,y:e.clientY,dx:e.deltaX,dy:e.deltaY}), true);
  // `v` reports whether this tab is the one on screen, so followers can switch to
  // the same tab the user switched to.
  window.__drain = () => JSON.stringify({v: !document.hidden, e: q.splice(0, q.length)});
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
                "modifiers": int(event.get("mod") or 0),
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
            # Without modifiers a follower misses Shift/Ctrl combos (Ctrl+A, Ctrl+V).
            "modifiers": int(event.get("mod") or 0),
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


def _main_context(browser: Any) -> Any | None:
    """The browser's persistent context (profiles launch exactly one)."""
    return browser.contexts[0] if browser.contexts else None


def _open_pages(context: Any) -> list[Any]:
    return [page for page in context.pages if not page.is_closed()]


async def _visible_page(pages: list[Any]) -> Any:
    """The tab the user is looking at, falling back to the first."""
    for page in pages:
        try:
            if await page.evaluate("!document.hidden"):
                return page
        except Exception:
            continue
    return pages[0]


async def broadcast(
    targets: list[tuple[str, str]], *, url: str | None = None, text: str | None = None
) -> list[dict]:
    """Open a URL, or type text, on every given profile's active tab.

    Independent of a sync session: it drives each profile's own CDP endpoint
    directly, so it needs no control window, steals no focus, and works on
    background windows — unlike OS-level input, which only reaches the foreground.
    Never closes a browser; these are the user's live windows.
    """
    from playwright.async_api import async_playwright

    results: list[dict] = []
    pw = await async_playwright().start()
    try:
        for profile_id, endpoint in targets:
            try:
                browser = await pw.chromium.connect_over_cdp(endpoint)
                context = _main_context(browser)
                pages = _open_pages(context) if context is not None else []
                if not pages:
                    results.append(
                        {"profile_id": profile_id, "ok": False, "error": "not_running"}
                    )
                    continue
                page = await _visible_page(pages)
                if url:
                    await page.goto(url, wait_until="commit", timeout=20000)
                else:
                    cdp = await page.context.new_cdp_session(page)
                    await cdp.send("Input.insertText", {"text": text or ""})
                results.append({"profile_id": profile_id, "ok": True, "error": None})
            except Exception:
                results.append({"profile_id": profile_id, "ok": False, "error": "failed"})
    finally:
        try:
            await pw.stop()
        except Exception:
            pass
    return results


class InputSyncService:
    """Mirrors input from a control profile to followers over CDP. One session at a
    time; hung on app.state so routes can start/stop/query it."""

    # Drain cadence. 50ms keeps mirrored input imperceptible while costing ~20 cheap
    # CDP evaluates/sec on one page.
    _POLL_SECONDS = 0.05
    # Safety rail: mirror at most this many tabs so a runaway popup loop in the
    # control can't spawn unbounded tabs across every follower.
    _MAX_TABS = 20

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

    async def _drain(self, ccdp: Any, context_id: int) -> tuple[bool, list[dict]]:
        """(is this tab on screen, buffered events) from a control tab."""
        result = await ccdp.send(
            "Runtime.evaluate",
            {
                "expression": "window.__drain()",
                "contextId": context_id,
                "returnByValue": True,
            },
        )
        try:
            payload = json.loads(result.get("result", {}).get("value") or "{}")
            return bool(payload.get("v")), list(payload.get("e") or [])
        except (ValueError, TypeError, AttributeError):
            return False, []

    async def _activate_tab(self, index: int, follower_ctxs: list[Any]) -> None:
        """Show the same-numbered tab in every follower window."""
        for context in follower_ctxs:
            pages = _open_pages(context)
            if index < len(pages):
                try:
                    await pages[index].bring_to_front()
                except Exception:
                    pass

    async def _ensure_armed(self, page: Any, tabs: dict, control_ctx: Any,
                            follower_ctxs: list[Any]) -> dict | None:
        """Give a control tab its CDP session + isolated-world capture. Idempotent;
        re-arms after a navigation destroyed the previous world."""
        entry = tabs.get(page)
        if entry is None:
            cdp = await page.context.new_cdp_session(page)
            await cdp.send("Page.enable")
            entry = {"cdp": cdp, "context_id": None, "stale": True}
            tabs[page] = entry
            loop = asyncio.get_running_loop()

            def _on_nav(frame: Any, _page=page, _entry=entry) -> None:
                if frame != _page.main_frame:
                    return
                _entry["stale"] = True  # the isolated world died with the document
                url = frame.url or ""
                if url and not url.startswith(("about:", "chrome:", "devtools:", "data:")):
                    loop.create_task(
                        self._mirror_nav(_page, url, control_ctx, follower_ctxs)
                    )

            page.on("framenavigated", _on_nav)
        if entry["stale"]:
            entry["context_id"] = await self._arm(entry["cdp"])
            entry["stale"] = False
        return entry

    async def _mirror_tab_count(
        self, control_count: int, previous: int, follower_ctxs: list[Any]
    ) -> int:
        """Mirror *changes* to the control's tab count — open a tab in the control and
        each follower opens one; close one and each follower closes its extra.

        Deliberately not "keep the counts equal": enforcing equality every tick
        re-opened any tab the user closed in a follower window, which made closing a
        synced profile impossible.
        """
        if control_count == previous:
            return previous
        delta = control_count - previous
        for context in follower_ctxs:
            browser = context.browser
            if browser is not None and not browser.is_connected():
                continue  # that follower is gone; don't resurrect it
            try:
                if delta > 0:
                    for _ in range(delta):
                        await context.new_page()
                else:
                    for page in _open_pages(context)[control_count:]:
                        await page.close()
            except Exception:
                pass  # a follower that races us is retried on the next change
        return control_count

    async def _follower_cdp(self, page: Any, cache: dict) -> Any:
        session = cache.get(page)
        if session is None:
            session = await page.context.new_cdp_session(page)
            cache[page] = session
        return session

    async def _run(self, control_endpoint, follower_endpoints, ready) -> None:
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        try:
            control = await pw.chromium.connect_over_cdp(control_endpoint)
            control_ctx = _main_context(control)
            if control_ctx is None or not _open_pages(control_ctx):
                raise RuntimeError("control_has_no_page")

            follower_ctxs: list[Any] = []
            for endpoint in follower_endpoints:
                browser = await pw.chromium.connect_over_cdp(endpoint)
                context = _main_context(browser)
                if context is not None:
                    follower_ctxs.append(context)

            tabs: dict = {}  # control page -> capture state
            follower_sessions: dict = {}  # follower page -> cdp session
            active_index: int | None = None  # control tab currently on screen
            tab_count = len(_open_pages(control_ctx))

            await self._ensure_armed(
                _open_pages(control_ctx)[0], tabs, control_ctx, follower_ctxs
            )
            if not ready.done():
                ready.set_result(None)

            while True:
                try:  # doubles as the poll tick and the stop signal
                    await asyncio.wait_for(self._stop.wait(), timeout=self._POLL_SECONDS)
                    break
                except asyncio.TimeoutError:
                    pass

                # The synced windows are gone (profile stopped, or the user closed
                # the last tab) — end the session so it stops reporting itself as
                # active and the UI can offer Start again.
                if not control.is_connected() or not _open_pages(control_ctx):
                    break
                if not any(
                    context.browser is not None and context.browser.is_connected()
                    for context in follower_ctxs
                ):
                    break

                control_pages = _open_pages(control_ctx)[: self._MAX_TABS]
                tab_count = await self._mirror_tab_count(
                    len(control_pages), tab_count, follower_ctxs
                )

                visible_index: int | None = None
                for index, page in enumerate(control_pages):
                    try:
                        entry = await self._ensure_armed(
                            page, tabs, control_ctx, follower_ctxs
                        )
                    except Exception:
                        continue  # document still settling; retry next tick
                    try:
                        visible, events = await self._drain(
                            entry["cdp"], entry["context_id"]
                        )
                    except Exception:
                        # Context destroyed under us (a navigation raced the drain) —
                        # re-arm next tick rather than ending the session.
                        entry["stale"] = True
                        continue
                    if visible:
                        visible_index = index
                    for event in events:
                        await self._fanout(event, index, follower_ctxs, follower_sessions)

                # The user switched tabs in the control -> show the same tab in every
                # follower. Without this the follower still *receives* the mirrored
                # input on the right tab, but keeps displaying the old one.
                if visible_index is not None and visible_index != active_index:
                    active_index = visible_index
                    await self._activate_tab(active_index, follower_ctxs)
        except Exception as error:  # noqa: BLE001 — surface to the awaiting caller
            if not ready.done():
                ready.set_exception(error)
        finally:
            # Deliberately no browser.close(): these are the user's live profile
            # windows, connected to over CDP, not browsers we launched. Stopping the
            # driver drops our connections and leaves every profile running.
            try:
                await pw.stop()
            except Exception:
                pass

    async def _fanout(self, event: dict, index: int, follower_ctxs: list[Any],
                      sessions: dict) -> None:
        """Replay one control-tab event on the same-numbered tab of every follower."""
        commands = translate_event(event)
        if not commands:
            return
        for context in follower_ctxs:
            pages = _open_pages(context)
            if index >= len(pages):
                continue  # follower hasn't opened this tab yet
            try:
                cdp = await self._follower_cdp(pages[index], sessions)
                for method, params in commands:
                    await cdp.send(method, params)
            except Exception:
                pass

    async def _mirror_nav(self, page: Any, url: str, control_ctx: Any,
                          follower_ctxs: list[Any]) -> None:
        """Navigate the same-numbered follower tab. The index is resolved when the
        navigation fires, so it stays correct as tabs open and close."""
        pages = _open_pages(control_ctx)
        if page not in pages:
            return
        index = pages.index(page)
        for context in follower_ctxs:
            fpages = _open_pages(context)
            if index >= len(fpages):
                continue
            try:
                await fpages[index].goto(url, wait_until="commit", timeout=15000)
            except Exception:
                pass
