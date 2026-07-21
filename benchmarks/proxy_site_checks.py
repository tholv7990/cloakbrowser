"""Passive, credential-safe browser checks for two protected-site demos.

These checks report only observed page-state verdicts.  They do not submit,
click, retry, or otherwise interact with challenges.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import ipaddress
import json
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlsplit

from cloakbrowser import launch_persistent_context, maybe_resolve_geoip


_CLOUDFLARE_URL = "https://turnstiledemo.lusostreams.com/"
_GOOGLE_QUERY_URL = "https://www.google.com/search?q=cloakbrowser+browser+compatibility"
_IDENTITY_URL = "https://api.ipify.org?format=json"
_IDENTITY_TIMEOUT_SECONDS = 10.0
_CLOUDFLARE_TIMEOUT_SECONDS = 20.0
_GOOGLE_TIMEOUT_SECONDS = 15.0
_SCREENSHOT_TIMEOUT_MS = 2_000
_POLL_SECONDS = 0.25
_CLOUDFLARE_TOKEN_SELECTOR = 'input[name="cf-turnstile-response"]'
_CLOUDFLARE_CHALLENGE_SELECTORS = (
    "#challenge-form",
    "[data-testid='challenge-running']",
)
_CLOUDFLARE_WIDGET_SELECTORS = (
    ".cf-turnstile",
    "[data-sitekey]",
    "iframe[src*='challenges.cloudflare.com']",
)
_CLOUDFLARE_FRAME_SELECTOR = "iframe[src*='challenges.cloudflare.com']"
_CLOUDFLARE_FRAME_INTERACTION_SELECTORS = (
    "input[type='checkbox']",
    "[role='checkbox']",
    "label:has(input[type='checkbox'])",
    "text=Verify you are human",
)
_GOOGLE_RECAPTCHA_SELECTORS = (
    ".g-recaptcha",
    "#recaptcha",
    "iframe[src*='recaptcha']",
)
_WEBRTC_OBSERVATION_SCRIPT = """
async () => {
  const result = {
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || null,
    locale: navigator.language || null,
    webrtc_candidates: [],
  };
  if (typeof RTCPeerConnection !== "function") return result;
  const peer = new RTCPeerConnection({iceServers: []});
  try {
    peer.createDataChannel("identity-observation");
    peer.onicecandidate = event => {
      if (event.candidate && event.candidate.candidate) {
        result.webrtc_candidates.push(event.candidate.candidate);
      }
    };
    const offer = await peer.createOffer();
    await peer.setLocalDescription(offer);
    await new Promise(resolve => {
      const timer = setTimeout(resolve, 1500);
      peer.addEventListener("icegatheringstatechange", () => {
        if (peer.iceGatheringState === "complete") {
          clearTimeout(timer);
          resolve();
        }
      });
    });
  } catch (_) {
    // Missing WebRTC evidence remains explicit unknown in the Python model.
  } finally {
    peer.close();
  }
  return result;
}
"""


def parse_google_state(
    url: str,
    body_text: str,
    *,
    search_container_visible: bool,
    recaptcha_visible: bool,
) -> str:
    """Return a passive Google page-state verdict from safe observations."""

    path = urlsplit(url).path.lower()
    normalized = " ".join(body_text.lower().split())
    if "/sorry/" in path or recaptcha_visible:
        return "captcha"
    if _has_google_access_denial(normalized):
        return "blocked"
    if search_container_visible:
        return "results"
    if _is_google_consent(url, normalized):
        return "consent"
    return "unknown"


def parse_cloudflare_state(
    body_text: str,
    *,
    token_present: bool,
    challenge_visible: bool,
    url: str = "",
    status_code: int | None = None,
) -> str:
    """Return a passive Cloudflare Turnstile widget-state verdict."""

    normalized = " ".join(body_text.lower().split())
    if token_present and not challenge_visible:
        return "passed"
    if challenge_visible:
        return "interactive"
    if _has_cloudflare_block(url, status_code, normalized):
        return "blocked"
    if _has_cloudflare_error(normalized):
        return "error"
    if _has_cloudflare_widget(normalized):
        return "pending"
    return "unknown"


def parse_webrtc_candidate_ips(candidates: object) -> dict[str, object]:
    """Extract only canonical IP and mDNS-presence evidence from ICE candidates."""

    observed: set[str] = set()
    mdns_observed = False
    if isinstance(candidates, Sequence) and not isinstance(candidates, (str, bytes, bytearray)):
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            fields = candidate.split()
            if len(fields) < 5 or not fields[0].lower().startswith("candidate:"):
                continue
            address = fields[4].strip("[]")
            if address.lower().endswith(".local"):
                mdns_observed = True
                continue
            try:
                observed.add(str(ipaddress.ip_address(address)))
            except ValueError:
                continue
    return {
        "observed_ips": sorted(observed),
        "mdns_candidate_observed": mdns_observed,
    }


def _canonical_ip(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def _comparison(expected: object, observed: object) -> bool | None:
    if not isinstance(expected, str) or not expected or not isinstance(observed, str) or not observed:
        return None
    return expected == observed


def build_identity_alignment(
    *,
    expected_exit_ip: str,
    http_exit_ip: str | None,
    webrtc_candidates: object,
    expected_timezone: str | None,
    observed_timezone: str | None,
    expected_locale: str | None,
    observed_locale: str | None,
    dns_proxied: bool | None,
) -> dict[str, object]:
    """Build field-attributed, tri-state browser identity evidence."""

    expected_ip = _canonical_ip(expected_exit_ip)
    observed_http_ip = _canonical_ip(http_exit_ip)
    http_matches = (
        expected_ip == observed_http_ip if expected_ip is not None and observed_http_ip is not None else None
    )
    webrtc = parse_webrtc_candidate_ips(webrtc_candidates)
    observed_webrtc = webrtc["observed_ips"]
    webrtc_matches = (
        observed_webrtc == [expected_ip]
        if expected_ip is not None and isinstance(observed_webrtc, list) and observed_webrtc
        else None
    )
    timezone_matches = _comparison(expected_timezone, observed_timezone)
    locale_matches = _comparison(expected_locale, observed_locale)
    dns_matches = dns_proxied if isinstance(dns_proxied, bool) else None
    comparisons = [
        http_matches,
        webrtc_matches,
        timezone_matches,
        locale_matches,
        dns_matches,
    ]
    complete = all(value is not None for value in comparisons)
    aligned = all(value is True for value in comparisons)
    mismatch = any(value is False for value in comparisons)
    status = "mismatch" if mismatch else ("aligned" if aligned else "unknown")
    return {
        "status": status,
        "aligned": False if mismatch else (True if aligned else None),
        "complete": complete,
        "http_exit_ip": {
            "source": "browser_ipify",
            "expected": expected_ip,
            "observed": observed_http_ip,
            "matches": http_matches,
        },
        "webrtc": {
            "source": "browser_rtc_peer_connection",
            "expected": expected_ip,
            **webrtc,
            "matches": webrtc_matches,
        },
        "timezone": {
            "source": "browser_intl",
            "expected": expected_timezone,
            "observed": observed_timezone,
            "matches": timezone_matches,
        },
        "locale": {
            "source": "browser_navigator",
            "expected": expected_locale,
            "observed": observed_locale,
            "matches": locale_matches,
        },
        "dns": {
            "source": "loopback_proxy_relay",
            "status": (
                "proxied" if dns_proxied is True else ("local" if dns_proxied is False else "unknown")
            ),
            "matches": dns_matches,
        },
    }


def _unknown_identity() -> dict[str, object]:
    return {"status": "unknown", "aligned": None, "complete": False}


def _relay_context(proxy: str):
    # Lazy import keeps deterministic parser tests independent from socket setup.
    from benchmarks.proxy_auth_relay import AuthenticatedProxyRelay

    return AuthenticatedProxyRelay(proxy)


def _relay_dns_proxied(relay: object) -> bool | None:
    observations = getattr(relay, "dns_observations", None)
    if isinstance(observations, Sequence) and not isinstance(
        observations, (str, bytes, bytearray)
    ):
        delegations = {
            item.get("delegation")
            for item in observations
            if isinstance(item, Mapping) and item.get("destination_type") == "hostname"
        }
        if "local" in delegations:
            return False
        if "upstream" in delegations:
            return True
        return None
    fallback = getattr(relay, "dns_proxied", None)
    return fallback if isinstance(fallback, bool) else None


def run_browser_checks(
    proxy: str,
    profile_dir: Path,
    screenshot_dir: Path,
    *,
    expected_exit_ip: str | None = None,
) -> dict[str, object]:
    """Passively inspect one Cloudflare demo and one fixed Google query.

    Only string verdicts and screenshot-success booleans are returned.  The
    proxy, browser profile, page contents, cookies, headers, and any widget
    response token remain local to the running browser and are never returned.
    """

    results: dict[str, object] = {
        "identity": _unknown_identity(),
        "cloudflare": {"verdict": "error", "screenshot_captured": False},
        "google": {"verdict": "unknown", "screenshot_captured": False},
    }
    screenshot_dir = Path(screenshot_dir)
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    try:
        with _relay_context(proxy) as relay:
            expected_timezone: str | None = None
            expected_locale: str | None = None
            try:
                expected_timezone, expected_locale, _ = maybe_resolve_geoip(
                    True, relay.browser_proxy_url, None, None
                )
            except Exception:
                pass
            try:
                context = launch_persistent_context(
                    str(profile_dir),
                    proxy=relay.browser_proxy_url,
                    geoip=True,
                    timezone=expected_timezone,
                    locale=expected_locale,
                    humanize=True,
                    fingerprint_preset="consistent",
                    args=["--fingerprint=63003"],
                )
            except Exception:
                return results

            try:
                page = context.pages[0] if context.pages else context.new_page()
                results["identity"] = _check_identity(
                    page,
                    expected_exit_ip=expected_exit_ip,
                    expected_timezone=expected_timezone,
                    expected_locale=expected_locale,
                    relay=relay,
                )
                results["cloudflare"] = _check_cloudflare(page, screenshot_dir / "cloudflare.png")
                results["google"] = _check_google(page, screenshot_dir / "google.png")
            except Exception:
                # Avoid surfacing browser transport errors: some include proxy URLs.
                pass
            finally:
                try:
                    context.close()
                except Exception:
                    pass
    except Exception:
        # Relay errors can include upstream socket detail.  Return only safe states.
        return results
    return results


def run_direct_google_control(profile_dir: Path, screenshot_path: Path) -> dict[str, object]:
    """Run one credential-free Google control, separate from every proxy report."""

    result: dict[str, object] = {"verdict": "unknown", "screenshot_captured": False}
    try:
        context = launch_persistent_context(
            str(profile_dir),
            geoip=True,
            humanize=True,
            fingerprint_preset="consistent",
            args=["--fingerprint=63003"],
        )
    except Exception:
        return result
    try:
        page = context.pages[0] if context.pages else context.new_page()
        return _check_google(page, Path(screenshot_path))
    except Exception:
        return result
    finally:
        try:
            context.close()
        except Exception:
            pass


def _check_identity(
    page: object,
    *,
    expected_exit_ip: str | None,
    expected_timezone: str | None,
    expected_locale: str | None,
    relay: object,
) -> dict[str, object]:
    if not expected_exit_ip:
        return _unknown_identity()
    deadline = monotonic() + _IDENTITY_TIMEOUT_SECONDS
    http_exit_ip: str | None = None
    observed_timezone: str | None = None
    observed_locale: str | None = None
    webrtc_candidates: object = []
    try:
        response = page.goto(  # type: ignore[attr-defined]
            _IDENTITY_URL,
            wait_until="domcontentloaded",
            timeout=_remaining_timeout_ms(deadline),
        )
        if response is not None and _response_status(response) >= 400:
            raise RuntimeError("identity endpoint unavailable")
        body = _body_text(page, timeout_ms=_remaining_timeout_ms(deadline))
        payload = json.loads(body)
        if isinstance(payload, Mapping):
            http_exit_ip = _canonical_ip(payload.get("ip"))
        browser_values = page.evaluate(_WEBRTC_OBSERVATION_SCRIPT)  # type: ignore[attr-defined]
        if isinstance(browser_values, Mapping):
            timezone_value = browser_values.get("timezone")
            locale_value = browser_values.get("locale")
            observed_timezone = timezone_value if isinstance(timezone_value, str) else None
            observed_locale = locale_value if isinstance(locale_value, str) else None
            webrtc_candidates = browser_values.get("webrtc_candidates", [])
    except Exception:
        pass
    return build_identity_alignment(
        expected_exit_ip=expected_exit_ip,
        http_exit_ip=http_exit_ip,
        webrtc_candidates=webrtc_candidates,
        expected_timezone=expected_timezone,
        observed_timezone=observed_timezone,
        expected_locale=expected_locale,
        observed_locale=observed_locale,
        dns_proxied=_relay_dns_proxied(relay),
    )


def _check_cloudflare(page: object, screenshot_path: Path) -> dict[str, object]:
    deadline = monotonic() + _CLOUDFLARE_TIMEOUT_SECONDS
    state = "error"
    try:
        remaining_ms = _remaining_timeout_ms(deadline)
        if remaining_ms > 0:
            response = page.goto(  # type: ignore[attr-defined]
                _CLOUDFLARE_URL, wait_until="domcontentloaded", timeout=remaining_ms
            )
            state = _wait_for_cloudflare_state(
                page, deadline=deadline, status_code=_response_status(response)
            )
    except Exception:
        state = "error"
    return {
        "verdict": state,
        "screenshot_captured": _capture_screenshot(page, screenshot_path),
    }


def _check_google(page: object, screenshot_path: Path) -> dict[str, object]:
    deadline = monotonic() + _GOOGLE_TIMEOUT_SECONDS
    state = "unknown"
    try:
        remaining_ms = _remaining_timeout_ms(deadline)
        if remaining_ms > 0:
            page.goto(_GOOGLE_QUERY_URL, wait_until="domcontentloaded", timeout=remaining_ms)  # type: ignore[attr-defined]
            state = _wait_for_google_state(page, deadline=deadline)
    except Exception:
        state = "unknown"
    return {
        "verdict": state,
        "screenshot_captured": _capture_screenshot(page, screenshot_path),
    }


def _wait_for_cloudflare_state(
    page: object, *, deadline: float, status_code: int | None = None
) -> str:
    state = "unknown"
    awaiting_interaction = False
    while True:
        remaining_ms = _remaining_timeout_ms(deadline)
        if remaining_ms <= 0:
            return "interactive" if state == "pending" and awaiting_interaction else state
        body_text = _body_text(page, timeout_ms=remaining_ms)
        challenge_visible = _any_visible_before_deadline(
            page, _CLOUDFLARE_CHALLENGE_SELECTORS, deadline
        )
        frame_interaction_visible = _turnstile_frame_interaction_visible(
            page, deadline
        )
        state = parse_cloudflare_state(
            body_text,
            token_present=_token_present(page, timeout_ms=_remaining_timeout_ms(deadline)),
            challenge_visible=challenge_visible,
            url=_page_url(page),
            status_code=status_code,
        )
        widget_visible = frame_interaction_visible or _any_visible_before_deadline(
            page, _CLOUDFLARE_WIDGET_SELECTORS, deadline
        )
        if state == "unknown" and widget_visible:
            state = "pending"
        awaiting_interaction = widget_visible and frame_interaction_visible
        if state in {"passed", "interactive", "blocked", "error"} or monotonic() >= deadline:
            return (
                "interactive"
                if state == "pending" and awaiting_interaction
                else state
            )
        _wait_briefly(page, timeout_ms=min(int(_POLL_SECONDS * 1_000), _remaining_timeout_ms(deadline)))


def _wait_for_google_state(page: object, *, deadline: float) -> str:
    state = "unknown"
    while True:
        remaining_ms = _remaining_timeout_ms(deadline)
        if remaining_ms <= 0:
            return state
        state = parse_google_state(
            _page_url(page),
            _body_text(page, timeout_ms=remaining_ms),
            search_container_visible=_is_visible(
                page, "#search", timeout_ms=_remaining_timeout_ms(deadline)
            ),
            recaptcha_visible=_any_visible_before_deadline(
                page, _GOOGLE_RECAPTCHA_SELECTORS, deadline
            ),
        )
        if state in {"results", "captcha", "consent", "blocked"} or monotonic() >= deadline:
            return state
        _wait_briefly(page, timeout_ms=min(int(_POLL_SECONDS * 1_000), _remaining_timeout_ms(deadline)))


def _has_google_access_denial(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "access denied",
            "you don't have permission to access",
            "you do not have permission to access",
        )
    )


def _is_google_consent(url: str, text: str) -> bool:
    hostname = urlsplit(url).hostname or ""
    return hostname.lower() == "consent.google.com" or "before you continue to google" in text


def _has_cloudflare_error(text: str) -> bool:
    return text in {"error", "error!"} or text.startswith("error:") or any(
        phrase in text
        for phrase in (
            "error 1",
            "error 5",
            "error 10",
            "something went wrong",
            "worker threw exception",
        )
    )


def _has_cloudflare_block(url: str, status_code: int | None, text: str) -> bool:
    path = urlsplit(url).path.lower()
    return (
        status_code in {401, 403, 429}
        or "/cdn-cgi/challenge-platform/block" in path
        or any(
            phrase in text
            for phrase in (
                "error 1020",
                "access denied",
                "rate limited",
                "temporarily blocked",
            )
        )
    )


def _has_cloudflare_widget(text: str) -> bool:
    return "turnstile" in text or "cloudflare widget" in text


def _turnstile_frame_interaction_visible(page: object, deadline: float) -> bool:
    """Passively detect a managed Turnstile checkbox inside its iframe."""

    try:
        frame = page.frame_locator(_CLOUDFLARE_FRAME_SELECTOR).first  # type: ignore[attr-defined]
    except Exception:
        return False
    for selector in _CLOUDFLARE_FRAME_INTERACTION_SELECTORS:
        timeout_ms = _remaining_timeout_ms(deadline)
        if timeout_ms <= 0:
            return False
        try:
            if frame.locator(selector).first.is_visible(timeout=timeout_ms):
                return True
        except Exception:
            continue
    return False


def _body_text(page: object, *, timeout_ms: int) -> str:
    if timeout_ms <= 0:
        return ""
    try:
        return str(page.locator("body").inner_text(timeout=timeout_ms))  # type: ignore[attr-defined]
    except Exception:
        return ""


def _page_url(page: object) -> str:
    try:
        return str(page.url)  # type: ignore[attr-defined]
    except Exception:
        return ""


def _token_present(page: object, *, timeout_ms: int) -> bool:
    if timeout_ms <= 0:
        return False
    try:
        # Compute only a boolean inside the page.  Turnstile demos can render
        # several response inputs, and returning their values would retain
        # sensitive challenge material outside the browser context.
        return page.locator(_CLOUDFLARE_TOKEN_SELECTOR).evaluate_all(  # type: ignore[attr-defined]
            """elements => elements.some(element =>
                typeof element.value === "string" && element.value.trim().length > 0
            )"""
        ) is True
    except Exception:
        return False


def _is_visible(page: object, selector: str, *, timeout_ms: int) -> bool:
    if timeout_ms <= 0:
        return False
    try:
        return bool(page.locator(selector).first.is_visible(timeout=timeout_ms))  # type: ignore[attr-defined]
    except Exception:
        return False


def _any_visible_before_deadline(page: object, selectors: tuple[str, ...], deadline: float) -> bool:
    for selector in selectors:
        if _is_visible(page, selector, timeout_ms=_remaining_timeout_ms(deadline)):
            return True
    return False


def _wait_briefly(page: object, *, timeout_ms: int) -> None:
    if timeout_ms <= 0:
        return
    try:
        page.wait_for_timeout(timeout_ms)  # type: ignore[attr-defined]
    except Exception:
        sleep(timeout_ms / 1_000)


def _capture_screenshot(page: object, path: Path) -> bool:
    try:
        page.screenshot(  # type: ignore[attr-defined]
            path=str(path), full_page=True, timeout=_SCREENSHOT_TIMEOUT_MS
        )
        return True
    except Exception:
        return False


def _remaining_timeout_ms(deadline: float) -> int:
    """Return the unspent portion of a site deadline as a Playwright timeout."""

    return max(0, int((deadline - monotonic()) * 1_000))


def _response_status(response: object) -> int:
    try:
        status = response.status  # type: ignore[attr-defined]
    except Exception:
        return 0
    return status if isinstance(status, int) else 0
