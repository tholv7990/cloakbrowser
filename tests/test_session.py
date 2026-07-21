from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class SyncBrowser:
    def __init__(self):
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class AsyncBrowser:
    def __init__(self):
        self.close_calls = 0

    async def close(self):
        self.close_calls += 1


def test_sync_session_reuses_one_driver_and_cleans_leaked_browsers():
    from cloakbrowser.session import CloakBrowserSession

    pw = MagicMock()
    starter = MagicMock()
    starter.start.return_value = pw
    first, second = SyncBrowser(), SyncBrowser()

    with patch("cloakbrowser.session.sync_playwright", return_value=starter), patch(
        "cloakbrowser.session._launch_with_playwright", side_effect=[first, second]
    ) as launch:
        with CloakBrowserSession() as session:
            assert session.launch(headless=True) is first
            assert session.launch(headless=False) is second
            first.close()
            assert pw.stop.call_count == 0

    assert starter.start.call_count == 1
    assert launch.call_count == 2
    assert first.close_calls == 1
    assert second.close_calls == 1
    assert pw.stop.call_count == 1


def test_sync_session_rejects_invalid_lifecycle_and_close_is_idempotent():
    from cloakbrowser.session import CloakBrowserSession

    session = CloakBrowserSession()
    with pytest.raises(RuntimeError, match="active"):
        session.launch()

    pw = MagicMock()
    starter = MagicMock()
    starter.start.return_value = pw
    with patch("cloakbrowser.session.sync_playwright", return_value=starter):
        session.__enter__()
        with pytest.raises(RuntimeError, match="already active"):
            session.__enter__()
        session.close()
        session.close()

    assert pw.stop.call_count == 1
    with pytest.raises(RuntimeError, match="active"):
        session.launch()


@pytest.mark.asyncio
async def test_async_session_reuses_one_driver_and_cleans_leaked_browsers():
    from cloakbrowser.session import AsyncCloakBrowserSession

    pw = MagicMock()
    pw.stop = AsyncMock()
    starter = MagicMock()
    starter.start = AsyncMock(return_value=pw)
    first, second = AsyncBrowser(), AsyncBrowser()

    with patch("cloakbrowser.session.async_playwright", return_value=starter), patch(
        "cloakbrowser.session._launch_with_playwright_async",
        AsyncMock(side_effect=[first, second]),
    ) as launch:
        async with AsyncCloakBrowserSession() as session:
            assert await session.launch(headless=True) is first
            assert await session.launch(headless=False) is second
            await first.close()
            assert pw.stop.await_count == 0

    assert starter.start.await_count == 1
    assert launch.await_count == 2
    assert first.close_calls == 1
    assert second.close_calls == 1
    assert pw.stop.await_count == 1


@pytest.mark.asyncio
async def test_async_session_rejects_invalid_lifecycle_and_close_is_idempotent():
    from cloakbrowser.session import AsyncCloakBrowserSession

    session = AsyncCloakBrowserSession()
    with pytest.raises(RuntimeError, match="active"):
        await session.launch()

    pw = MagicMock()
    pw.stop = AsyncMock()
    starter = MagicMock()
    starter.start = AsyncMock(return_value=pw)
    with patch("cloakbrowser.session.async_playwright", return_value=starter):
        await session.__aenter__()
        with pytest.raises(RuntimeError, match="already active"):
            await session.__aenter__()
        await session.close()
        await session.close()

    assert pw.stop.await_count == 1
    with pytest.raises(RuntimeError, match="active"):
        await session.launch()
