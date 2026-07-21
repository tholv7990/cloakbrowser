"""Reusable Playwright driver sessions for repeated CloakBrowser launches."""

from __future__ import annotations

from typing import Any

from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright

from .browser import _launch_with_playwright, _launch_with_playwright_async


class CloakBrowserSession:
    """Synchronous reusable Playwright session.

    Enter once, then call :meth:`launch` repeatedly without paying Playwright's
    driver-start cost for each browser.
    """

    def __init__(self) -> None:
        self._pw: Any = None
        self._browsers: list[Any] = []

    def __enter__(self) -> "CloakBrowserSession":
        if self._pw is not None:
            raise RuntimeError("CloakBrowserSession is already active")
        self._pw = sync_playwright().start()
        return self

    def launch(self, **kwargs: Any) -> Any:
        if self._pw is None:
            raise RuntimeError("CloakBrowserSession must be active before launch")
        browser = _launch_with_playwright(self._pw, **kwargs)
        original_close = browser.close

        def close_and_forget() -> None:
            try:
                original_close()
            finally:
                self._browsers = [item for item in self._browsers if item is not browser]

        browser.close = close_and_forget
        self._browsers.append(browser)
        return browser

    def close(self) -> None:
        if self._pw is None:
            return
        browsers, self._browsers = self._browsers, []
        try:
            for browser in reversed(browsers):
                try:
                    browser.close()
                except Exception:
                    pass
        finally:
            pw, self._pw = self._pw, None
            pw.stop()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


class AsyncCloakBrowserSession:
    """Asynchronous reusable Playwright session."""

    def __init__(self) -> None:
        self._pw: Any = None
        self._browsers: list[Any] = []

    async def __aenter__(self) -> "AsyncCloakBrowserSession":
        if self._pw is not None:
            raise RuntimeError("AsyncCloakBrowserSession is already active")
        self._pw = await async_playwright().start()
        return self

    async def launch(self, **kwargs: Any) -> Any:
        if self._pw is None:
            raise RuntimeError("AsyncCloakBrowserSession must be active before launch")
        browser = await _launch_with_playwright_async(self._pw, **kwargs)
        original_close = browser.close

        async def close_and_forget() -> None:
            try:
                await original_close()
            finally:
                self._browsers = [item for item in self._browsers if item is not browser]

        browser.close = close_and_forget
        self._browsers.append(browser)
        return browser

    async def close(self) -> None:
        if self._pw is None:
            return
        browsers, self._browsers = self._browsers, []
        try:
            for browser in reversed(browsers):
                try:
                    await browser.close()
                except Exception:
                    pass
        finally:
            pw, self._pw = self._pw, None
            await pw.stop()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()
