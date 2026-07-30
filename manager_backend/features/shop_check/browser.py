"""Shop page interaction: the per-email flow and the coordinator's process_worker.

The coordinator provisions a proxy + profile per worker and launches the
browser; this module is the injected callback that actually drives the page for
each of the worker's emails: navigate to Shop, enter the email, submit, read the
resulting page, classify it, and — for a phone OTP — parse the masked number.
Between emails the Shop origin state is cleared so email N+1 starts fresh in the
same profile.

All browser I/O is behind the `ShopSession` protocol. Unit tests drive a fake;
production uses `CdpShopSession` (validated by the authenticated Windows smoke
test, not unit tests, exactly like the RuntimeManager launcher).

Security: the full email address is resolved from CredentialStore only at the
moment it is typed, is never written to a row/error/log, and only its masked
form + the classification result are persisted.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ...features.proxies.credentials import CredentialStore
from ...models import ShopCheckEmail
from . import service
from .classifier import classify
from .phone import PhoneInfo, parse_phone_hint

_logger = logging.getLogger(__name__)


class ShopSession(Protocol):
    """Semantic control surface over a launched Shop page (no raw selectors leak
    to callers)."""

    def goto(self, url: str) -> None: ...
    def fill_email(self, email: str) -> None: ...
    def submit(self) -> None: ...
    def page_html(self) -> str: ...
    def phone_hint(self) -> str | None: ...
    def clear_origin_state(self) -> None: ...
    def screenshot(self) -> bytes | None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class EmailOutcome:
    result: str
    phone: PhoneInfo | None = None


def check_email(session: ShopSession, email: str, *, target_url: str) -> EmailOutcome:
    """Drive one email through Shop and classify the result. Raises on a
    navigation/interaction failure — the caller maps that to navigation_failed."""
    session.goto(target_url)
    session.fill_email(email)
    session.submit()
    result = classify(session.page_html()).result
    phone = None
    if result == "phone_otp_required":
        hint = session.phone_hint()
        phone = parse_phone_hint(hint) if hint else None
    return EmailOutcome(result, phone)


def _resolve_email(store: CredentialStore, session_factory: Callable, email_id: str) -> str | None:
    """Fetch the full address for one email row from CredentialStore. Returns
    None if the row or secret is gone (treated as navigation_failed upstream)."""
    with session_factory() as session:
        row = session.get(ShopCheckEmail, email_id)
        ref = row.credential_ref if row is not None else None
    if ref is None:
        return None
    credential = store.get(ref)
    return credential.username if credential is not None else None


def _finalize(session_factory: Callable, email_id: str, outcome: EmailOutcome) -> None:
    phone = outcome.phone
    with session_factory() as session:
        email = session.get(ShopCheckEmail, email_id)
        if email is None or email.state == "terminal":
            return  # already finalized (cancel/retry raced) — never double-write
        service.finalize_email(
            session,
            email,
            outcome.result,
            phone_prefix=phone.prefix if phone else None,
            phone_suffix=phone.suffix if phone else None,
            phone_country_code=phone.country_code if phone else None,
            phone_country_name=phone.country_name if phone else None,
            phone_region_name=phone.region_name if phone else None,
            phone_confidence=phone.confidence if phone else None,
        )


def open_cdp_session(ctx: Any) -> ShopSession:
    """Production opener: connect to the worker's already-ready browser over its
    live CDP endpoint (the coordinator waited for readiness before calling us)."""
    return CdpShopSession(ctx.cdp_endpoint)


def make_process_worker(
    open_session: Callable[[Any], ShopSession],
    *,
    target_url: str = "https://shop.app/",
) -> Callable[[Any], None]:
    """Build the coordinator's injected `process_worker`.

    `open_session(ctx)` yields a live `ShopSession` for the worker's already-ready
    browser (production reads `ctx.cdp_endpoint`; tests return a fake). The
    returned callback processes each assigned email in order, honouring
    cancellation between emails (the coordinator marks any still-pending emails
    cancelled afterwards).
    """

    def process_worker(ctx: Any) -> None:
        session = open_session(ctx)
        try:
            for email_id in ctx.email_ids:
                if ctx.is_cancelled():
                    return  # leave the rest pending; coordinator cancels them
                email = _resolve_email(ctx.store, ctx.session_factory, email_id)
                if email is None:
                    _finalize(ctx.session_factory, email_id, EmailOutcome("navigation_failed"))
                    continue
                try:
                    outcome = check_email(session, email, target_url=target_url)
                except Exception:
                    # Never include the email/page text in the log or the row.
                    _logger.warning("shop_check: email interaction failed for %s", email_id)
                    outcome = EmailOutcome("navigation_failed")
                _finalize(ctx.session_factory, email_id, outcome)
                try:
                    session.clear_origin_state()
                except Exception:
                    _logger.warning("shop_check: clearing origin state failed for worker")
        finally:
            try:
                session.close()
            except Exception:
                pass

    return process_worker


# --- real adapter (Task-16 validated, not unit tested) ----------------------
# ponytail: the CDP scaffolding below (connect, content, screenshot, cookie/
# storage clear) is knowable and correct; the Shop-specific field/button/
# phone-hint locators are best-effort heuristics that MUST be validated and
# tuned against the live site in the authenticated Windows smoke test (Task 16),
# where selectors can be iterated with a real page. Upgrade path: pin the exact
# selectors once observed live.
class CdpShopSession:
    def __init__(self, cdp_endpoint: str, *, timeout_ms: int = 15000):
        from playwright.sync_api import sync_playwright  # lazy: only in production

        self._pw = sync_playwright().start()
        browser = self._pw.chromium.connect_over_cdp(cdp_endpoint)
        self._browser = browser
        context = browser.contexts[0]
        self._context = context
        self._page = context.pages[0] if context.pages else context.new_page()
        self._page.set_default_timeout(timeout_ms)

    def goto(self, url: str) -> None:
        self._page.goto(url, wait_until="domcontentloaded")

    def fill_email(self, email: str) -> None:
        self._page.get_by_role("textbox", name="email").first.fill(email)

    def submit(self) -> None:
        self._page.get_by_role("button", name="Continue").first.click()
        self._page.wait_for_load_state("networkidle")

    def page_html(self) -> str:
        return self._page.content()

    def phone_hint(self) -> str | None:
        # The masked phone is shown in the OTP prompt text; the classifier already
        # confirmed a phone OTP, so return the visible body text for parsing.
        try:
            return self._page.locator("body").inner_text()
        except Exception:
            return None

    def clear_origin_state(self) -> None:
        # Wipe Shop's cookies + storage so the next email is a clean session.
        cdp = self._context.new_cdp_session(self._page)
        cdp.send("Network.clearBrowserCookies")
        try:
            self._page.evaluate("localStorage.clear(); sessionStorage.clear();")
        except Exception:
            pass

    def screenshot(self) -> bytes | None:
        try:
            return self._page.screenshot()
        except Exception:
            return None

    def close(self) -> None:
        # Leave the browser running (the coordinator's launcher owns its lifecycle);
        # just detach the Playwright connection.
        try:
            self._browser.close()
        finally:
            self._pw.stop()
