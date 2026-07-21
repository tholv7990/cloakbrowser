"""Offline safety tests for protected-site browser state checks."""

import json
from pathlib import Path

import pytest

import benchmarks.proxy_site_checks as site_checks
from benchmarks.proxy_site_checks import (
    build_identity_alignment,
    parse_webrtc_candidate_ips,
    parse_cloudflare_state,
    parse_google_state,
    run_browser_checks,
    run_direct_google_control,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "proxy_quality"


def test_google_results_text_that_mentions_recaptcha_is_not_a_challenge():
    assert parse_google_state(
        "https://www.google.com/search?q=test",
        "A search result discussing reCAPTCHA performance",
        search_container_visible=True,
        recaptcha_visible=False,
    ) == "results"


def test_google_sorry_redirect_is_captcha():
    body = (FIXTURE_ROOT / "google_sorry.txt").read_text(encoding="utf-8")

    assert parse_google_state(
        "https://www.google.com/sorry/index?continue=x",
        body,
        search_container_visible=False,
        recaptcha_visible=True,
    ) == "captcha"


def test_google_explicit_access_denial_precedes_search_results():
    assert parse_google_state(
        "https://www.google.com/search?q=test",
        "Access Denied",
        search_container_visible=True,
        recaptcha_visible=False,
    ) == "blocked"


def test_google_consent_form_is_detected_from_sanitized_text():
    body = (FIXTURE_ROOT / "google_consent.txt").read_text(encoding="utf-8")

    assert parse_google_state(
        "https://consent.google.com/",
        body,
        search_container_visible=False,
        recaptcha_visible=False,
    ) == "consent"


def test_cloudflare_token_without_interaction_passes():
    assert parse_cloudflare_state("Success!", token_present=True, challenge_visible=False) == "passed"


def test_cloudflare_visible_challenge_precedes_explicit_error():
    body = (FIXTURE_ROOT / "cloudflare_error.txt").read_text(encoding="utf-8")

    assert parse_cloudflare_state(body, token_present=False, challenge_visible=True) == "interactive"


def test_cloudflare_explicit_error_is_reported():
    assert parse_cloudflare_state(
        "Error: validation failed", token_present=False, challenge_visible=False
    ) == "error"


def test_cloudflare_widget_without_verdict_is_pending():
    assert parse_cloudflare_state(
        "Cloudflare Turnstile widget is loading", token_present=False, challenge_visible=False
    ) == "pending"


@pytest.mark.parametrize(
    ("url", "status_code", "body"),
    [
        ("https://example.test/cdn-cgi/challenge-platform/block", 200, ""),
        ("https://example.test/", 403, ""),
        ("https://example.test/", 200, "Cloudflare Error 1020: Access denied"),
    ],
)
def test_cloudflare_explicit_block_indicators_are_reachable(url, status_code, body):
    assert parse_cloudflare_state(
        body,
        token_present=False,
        challenge_visible=False,
        url=url,
        status_code=status_code,
    ) == "blocked"


def test_webrtc_candidates_keep_only_safe_ip_observations():
    result = parse_webrtc_candidate_ips([
        "candidate:1 1 UDP 2122260223 203.0.113.80 54400 typ srflx",
        "candidate:2 1 UDP 2122194687 192.0.2.20 54401 typ host",
        "candidate:3 1 UDP 2122194687 randomized-name.local 54402 typ host",
        "provider-controlled non-candidate text",
    ])

    assert result == {
        "observed_ips": ["192.0.2.20", "203.0.113.80"],
        "mdns_candidate_observed": True,
    }


def test_identity_alignment_is_tri_state_and_field_attributed():
    aligned = build_identity_alignment(
        expected_exit_ip="203.0.113.80",
        http_exit_ip="203.0.113.80",
        webrtc_candidates=["candidate:1 1 UDP 1 203.0.113.80 5000 typ srflx"],
        expected_timezone="Asia/Ho_Chi_Minh",
        observed_timezone="Asia/Ho_Chi_Minh",
        expected_locale="vi-VN",
        observed_locale="vi-VN",
        dns_proxied=True,
    )
    unknown = build_identity_alignment(
        expected_exit_ip="203.0.113.80",
        http_exit_ip=None,
        webrtc_candidates=[],
        expected_timezone=None,
        observed_timezone="Etc/UTC",
        expected_locale=None,
        observed_locale="en-US",
        dns_proxied=None,
    )

    assert aligned["status"] == "aligned"
    assert aligned["aligned"] is True
    assert aligned["complete"] is True
    assert aligned["http_exit_ip"]["matches"] is True
    assert aligned["webrtc"]["matches"] is True
    assert aligned["timezone"]["matches"] is True
    assert aligned["locale"]["matches"] is True
    assert aligned["dns"]["status"] == "proxied"
    assert unknown["status"] == "unknown"
    assert unknown["aligned"] is None
    assert unknown["complete"] is False


def test_local_dns_delegation_is_an_identity_mismatch():
    result = build_identity_alignment(
        expected_exit_ip="203.0.113.80",
        http_exit_ip="203.0.113.80",
        webrtc_candidates=["candidate:1 1 UDP 1 203.0.113.80 5000 typ srflx"],
        expected_timezone="Etc/UTC",
        observed_timezone="Etc/UTC",
        expected_locale="en-US",
        observed_locale="en-US",
        dns_proxied=False,
    )

    assert result["status"] == "mismatch"
    assert result["complete"] is True
    assert result["dns"] == {
        "source": "loopback_proxy_relay",
        "status": "local",
        "matches": False,
    }


@pytest.mark.parametrize(
    ("observations", "expected"),
    [
        (({"delegation": "upstream", "destination_type": "hostname"},), True),
        (({"delegation": "local", "destination_type": "hostname"},), False),
        (({"delegation": "not_applicable", "destination_type": "ip"},), None),
    ],
)
def test_relay_dns_observations_are_reduced_without_hostnames(observations, expected):
    class Relay:
        dns_observations = observations

    assert site_checks._relay_dns_proxied(Relay()) is expected


def test_identity_mismatch_reports_each_failed_dimension():
    result = build_identity_alignment(
        expected_exit_ip="203.0.113.80",
        http_exit_ip="203.0.113.81",
        webrtc_candidates=["candidate:1 1 UDP 1 198.51.100.9 5000 typ srflx"],
        expected_timezone="Asia/Ho_Chi_Minh",
        observed_timezone="Etc/UTC",
        expected_locale="vi-VN",
        observed_locale="en-US",
        dns_proxied=True,
    )

    assert result["status"] == "mismatch"
    assert result["aligned"] is False
    assert result["http_exit_ip"]["matches"] is False
    assert result["webrtc"]["matches"] is False
    assert result["timezone"]["matches"] is False
    assert result["locale"]["matches"] is False


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def advance_ms(self, milliseconds: int):
        self.now += milliseconds / 1_000


class _TimedLocator:
    def __init__(self, page, selector: str):
        self._page = page
        self._selector = selector

    @property
    def first(self):
        return self

    def is_visible(self, *, timeout: int):
        self._page.observation_timeouts.append((self._page.url, self._selector, timeout))
        return self._selector in self._page.visible_selectors

    def input_value(self, *, timeout: int):
        self._page.observation_timeouts.append((self._page.url, self._selector, timeout))
        return self._page.token_value

    def evaluate_all(self, _expression: str):
        self._page.observation_timeouts.append(
            (self._page.url, self._selector, 0)
        )
        return any(value.strip() for value in self._page.token_values)

    def inner_text(self, *, timeout: int):
        self._page.observation_timeouts.append((self._page.url, self._selector, timeout))
        return self._page.body_text


class _TimedFrameElement:
    def __init__(self, page, selector: str):
        self._page = page
        self._selector = selector

    @property
    def first(self):
        return self

    def is_visible(self, *, timeout: int):
        self._page.observation_timeouts.append(
            (self._page.url, f"frame>>{self._selector}", timeout)
        )
        return self._selector in self._page.frame_visible_selectors


class _TimedFrameLocator:
    def __init__(self, page):
        self._page = page

    @property
    def first(self):
        return self

    def locator(self, selector: str):
        return _TimedFrameElement(self._page, selector)


class _TimedPage:
    def __init__(
        self,
        clock: _FakeClock,
        *,
        visible_selectors=(),
        frame_visible_selectors=(),
        body_text="",
        token_value="",
        token_values=None,
    ):
        self._clock = clock
        self.visible_selectors = set(visible_selectors)
        self.frame_visible_selectors = set(frame_visible_selectors)
        self.body_text = body_text
        self.token_values = list(token_values) if token_values is not None else [token_value]
        self.token_value = self.token_values[0] if self.token_values else ""
        self.url = "about:blank"
        self.goto_timeouts: list[tuple[str, int]] = []
        self.observation_timeouts: list[tuple[str, str, int]] = []

    def goto(self, url: str, *, timeout: int, **_kwargs):
        self.url = url
        self.goto_timeouts.append((url, timeout))
        self._clock.advance_ms(9_000 if url == site_checks._CLOUDFLARE_URL else 4_000)

    def locator(self, selector: str):
        return _TimedLocator(self, selector)

    def frame_locator(self, _selector: str):
        return _TimedFrameLocator(self)

    def wait_for_timeout(self, milliseconds: int):
        self._clock.advance_ms(milliseconds)

    def screenshot(self, **_kwargs):
        return None


def test_each_site_uses_one_deadline_for_navigation_and_polling(tmp_path, monkeypatch):
    clock = _FakeClock()
    page = _TimedPage(clock)

    class Context:
        pages = [page]

        def close(self):
            return None

    monkeypatch.setattr(site_checks, "monotonic", clock.monotonic)
    monkeypatch.setattr(site_checks, "launch_persistent_context", lambda *_args, **_kwargs: Context())
    monkeypatch.setattr(
        site_checks,
        "_check_identity",
        lambda *_args, **_kwargs: {
            "status": "unknown",
            "aligned": None,
            "complete": False,
        },
    )
    monkeypatch.setattr(site_checks, "_relay_context", lambda _proxy: _FakeRelayContext())

    result = run_browser_checks("http://proxy.example:8080", tmp_path / "profile", tmp_path / "shots")

    assert page.goto_timeouts == [
        (site_checks._CLOUDFLARE_URL, 20_000),
        (site_checks._GOOGLE_QUERY_URL, 15_000),
    ]
    cloudflare_observations = [
        timeout
        for url, _selector, timeout in page.observation_timeouts
        if url == site_checks._CLOUDFLARE_URL
    ]
    google_observations = [
        timeout
        for url, _selector, timeout in page.observation_timeouts
        if url == site_checks._GOOGLE_QUERY_URL
    ]
    assert max(cloudflare_observations) <= 11_000
    assert max(google_observations) <= 11_000
    assert clock.now == 35.0
    assert result == {
        "identity": {"status": "unknown", "aligned": None, "complete": False},
        "cloudflare": {"verdict": "unknown", "screenshot_captured": True},
        "google": {"verdict": "unknown", "screenshot_captured": True},
    }


def test_visible_cloudflare_widget_without_body_text_is_pending(monkeypatch):
    clock = _FakeClock()
    page = _TimedPage(clock, visible_selectors={".cf-turnstile"})
    page.url = site_checks._CLOUDFLARE_URL
    monkeypatch.setattr(site_checks, "monotonic", clock.monotonic)

    assert site_checks._wait_for_cloudflare_state(page, deadline=20.0) == "pending"


def _managed_turnstile_page(
    clock: _FakeClock,
    fixture: dict[str, object],
    *,
    checkbox_visible: bool | None = None,
    token_value: str = "",
    token_values: tuple[str, ...] | None = None,
) -> _TimedPage:
    visible_selectors: set[str] = set()
    if fixture.get("widget_visible") is True:
        visible_selectors.add(".cf-turnstile")
    if fixture.get("managed_frame_visible") is True:
        visible_selectors.update(
            {
                "iframe[src*='challenges.cloudflare.com']",
                "iframe[title*='Cloudflare security challenge']",
            }
        )
    has_checkbox = (
        fixture.get("unchecked_checkbox_visible") is True
        if checkbox_visible is None
        else checkbox_visible
    )
    return _TimedPage(
        clock,
        visible_selectors=visible_selectors,
        frame_visible_selectors={"input[type='checkbox']"} if has_checkbox else set(),
        body_text=str(fixture.get("body_text", "")),
        token_value=token_value,
        token_values=token_values,
    )


def test_managed_turnstile_checkbox_is_interactive_from_sanitized_live_fixture(
    monkeypatch,
):
    fixture = json.loads(
        (FIXTURE_ROOT / "cloudflare_managed_interactive.json").read_text(
            encoding="utf-8"
        )
    )
    clock = _FakeClock()
    page = _managed_turnstile_page(clock, fixture)
    page.url = site_checks._CLOUDFLARE_URL
    monkeypatch.setattr(site_checks, "monotonic", clock.monotonic)

    assert site_checks._wait_for_cloudflare_state(page, deadline=20.0) == "interactive"
    assert clock.now == 20.0


def test_managed_frame_checkbox_is_sufficient_interaction_evidence(monkeypatch):
    clock = _FakeClock()
    page = _TimedPage(
        clock,
        frame_visible_selectors={"input[type='checkbox']"},
    )
    page.url = site_checks._CLOUDFLARE_URL
    monkeypatch.setattr(site_checks, "monotonic", clock.monotonic)

    assert site_checks._wait_for_cloudflare_state(page, deadline=20.0) == "interactive"
    assert clock.now == 20.0


def test_managed_turnstile_waiting_without_checkbox_remains_pending(monkeypatch):
    fixture = json.loads(
        (FIXTURE_ROOT / "cloudflare_managed_interactive.json").read_text(
            encoding="utf-8"
        )
    )
    clock = _FakeClock()
    page = _managed_turnstile_page(clock, fixture, checkbox_visible=False)
    page.url = site_checks._CLOUDFLARE_URL
    monkeypatch.setattr(site_checks, "monotonic", clock.monotonic)

    assert site_checks._wait_for_cloudflare_state(page, deadline=20.0) == "pending"
    assert clock.now == 20.0


def test_managed_turnstile_success_token_precedes_generic_widget_frame(monkeypatch):
    fixture = json.loads(
        (FIXTURE_ROOT / "cloudflare_managed_interactive.json").read_text(
            encoding="utf-8"
        )
    )
    clock = _FakeClock()
    page = _managed_turnstile_page(
        clock,
        fixture,
        checkbox_visible=False,
        token_value="sanitized-fixture-token",
    )
    page.url = site_checks._CLOUDFLARE_URL
    monkeypatch.setattr(site_checks, "monotonic", clock.monotonic)

    assert site_checks._wait_for_cloudflare_state(page, deadline=20.0) == "passed"


def test_any_populated_turnstile_response_input_marks_generic_widget_passed(
    monkeypatch,
):
    fixture = json.loads(
        (FIXTURE_ROOT / "cloudflare_managed_interactive.json").read_text(
            encoding="utf-8"
        )
    )
    clock = _FakeClock()
    page = _managed_turnstile_page(
        clock,
        fixture,
        checkbox_visible=False,
        token_values=("", "sanitized-fixture-token"),
    )
    page.url = site_checks._CLOUDFLARE_URL
    monkeypatch.setattr(site_checks, "monotonic", clock.monotonic)

    assert "success" not in fixture["body_text"].lower()
    assert site_checks._wait_for_cloudflare_state(page, deadline=20.0) == "passed"


class _FakeLocator:
    def __init__(self, page, selector: str):
        self._page = page
        self._selector = selector

    @property
    def first(self):
        return self

    def is_visible(self, **_kwargs):
        return self._page.visible.get((self._page.url, self._selector), False)

    def input_value(self, **_kwargs):
        return self._page.token_values.get((self._page.url, self._selector), "")

    def evaluate_all(self, _expression: str):
        values = self._page.token_values.get((self._page.url, self._selector), "")
        if isinstance(values, str):
            values = [values]
        return any(isinstance(value, str) and value.strip() for value in values)

    def inner_text(self, **_kwargs):
        return self._page.body_texts.get(self._page.url, "")


class _FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.goto_urls: list[str] = []
        self.screenshots: list[Path] = []
        self.body_texts = {
            site_checks._IDENTITY_URL: '{"ip":"203.0.113.80"}',
            "https://turnstiledemo.lusostreams.com/": (
                FIXTURE_ROOT / "cloudflare_success.txt"
            ).read_text(encoding="utf-8"),
            "https://www.google.com/search?q=cloakbrowser+browser+compatibility": (
                FIXTURE_ROOT / "google_results_recaptcha_mention.txt"
            ).read_text(encoding="utf-8"),
        }
        self.visible = {
            (
                "https://www.google.com/search?q=cloakbrowser+browser+compatibility",
                "#search",
            ): True,
        }
        self.token_values = {
            (
                "https://turnstiledemo.lusostreams.com/",
                'input[name="cf-turnstile-response"]',
            ): "sanitized-test-token",
        }

    def goto(self, url: str, **_kwargs):
        self.goto_urls.append(url)
        self.url = url

    def locator(self, selector: str):
        return _FakeLocator(self, selector)

    def screenshot(self, *, path: str, **_kwargs):
        target = Path(path)
        target.write_bytes(b"png")
        self.screenshots.append(target)

    def evaluate(self, _script):
        return {
            "timezone": "Asia/Ho_Chi_Minh",
            "locale": "vi-VN",
            "webrtc_candidates": [
                "candidate:1 1 UDP 2122260223 203.0.113.80 54400 typ srflx"
            ],
        }


class _FakeContext:
    def __init__(self):
        self.page = _FakePage()
        self.pages = [self.page]
        self.closed = False

    def close(self):
        self.closed = True


class _FakeRelayContext:
    browser_proxy_url = "http://127.0.0.1:43123"
    dns_proxied = True

    def __init__(self):
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True


def test_browser_checks_launch_once_per_site_without_challenge_interaction(tmp_path, monkeypatch):
    context = _FakeContext()
    launch_calls = []

    def fake_launch(profile, **kwargs):
        launch_calls.append((profile, kwargs))
        return context

    monkeypatch.setattr("benchmarks.proxy_site_checks.launch_persistent_context", fake_launch)
    relay = _FakeRelayContext()
    monkeypatch.setattr(site_checks, "_relay_context", lambda _proxy: relay)
    monkeypatch.setattr(
        site_checks,
        "maybe_resolve_geoip",
        lambda *_args, **_kwargs: ("Asia/Ho_Chi_Minh", "vi-VN", "203.0.113.80"),
    )

    result = run_browser_checks(
        "http://user:password@proxy.example:8080",
        tmp_path / "profile",
        tmp_path / "shots",
        expected_exit_ip="203.0.113.80",
    )

    assert launch_calls == [
        (
            str(tmp_path / "profile"),
            {
                "proxy": "http://127.0.0.1:43123",
                "geoip": True,
                "timezone": "Asia/Ho_Chi_Minh",
                "locale": "vi-VN",
                "humanize": True,
                "fingerprint_preset": "consistent",
                "args": ["--fingerprint=63003"],
            },
        )
    ]
    assert context.page.goto_urls == [
        site_checks._IDENTITY_URL,
        "https://turnstiledemo.lusostreams.com/",
        "https://www.google.com/search?q=cloakbrowser+browser+compatibility",
    ]
    assert context.closed is True
    assert relay.closed is True
    assert result == {
        "identity": build_identity_alignment(
            expected_exit_ip="203.0.113.80",
            http_exit_ip="203.0.113.80",
            webrtc_candidates=[
                "candidate:1 1 UDP 2122260223 203.0.113.80 54400 typ srflx"
            ],
            expected_timezone="Asia/Ho_Chi_Minh",
            observed_timezone="Asia/Ho_Chi_Minh",
            expected_locale="vi-VN",
            observed_locale="vi-VN",
            dns_proxied=True,
        ),
        "cloudflare": {"verdict": "passed", "screenshot_captured": True},
        "google": {"verdict": "results", "screenshot_captured": True},
    }
    assert not any("sanitized-test-token" in repr(value) for value in result.values())


def test_browser_launch_failure_returns_safe_site_outcomes(tmp_path, monkeypatch):
    def failed_launch(*_args, **_kwargs):
        raise RuntimeError("proxy http://user:password@proxy.example:8080 failed")

    monkeypatch.setattr("benchmarks.proxy_site_checks.launch_persistent_context", failed_launch)
    relay = _FakeRelayContext()
    monkeypatch.setattr(site_checks, "_relay_context", lambda _proxy: relay)
    monkeypatch.setattr(
        site_checks,
        "maybe_resolve_geoip",
        lambda *_args, **_kwargs: (None, None, None),
    )

    result = run_browser_checks(
        "http://user:password@proxy.example:8080",
        tmp_path / "profile",
        tmp_path / "shots",
        expected_exit_ip="203.0.113.80",
    )

    assert result == {
        "identity": {"status": "unknown", "aligned": None, "complete": False},
        "cloudflare": {"verdict": "error", "screenshot_captured": False},
        "google": {"verdict": "unknown", "screenshot_captured": False},
    }
    assert relay.closed is True
    assert "user:password" not in repr(result)


def test_direct_google_control_is_separate_and_uses_no_proxy(tmp_path, monkeypatch):
    context = _FakeContext()
    launch_calls = []

    def fake_launch(profile, **kwargs):
        launch_calls.append((profile, kwargs))
        return context

    monkeypatch.setattr(site_checks, "launch_persistent_context", fake_launch)

    result = run_direct_google_control(
        tmp_path / "direct-profile", tmp_path / "direct-google.png"
    )

    assert launch_calls == [
        (
            str(tmp_path / "direct-profile"),
            {
                "geoip": True,
                "humanize": True,
                "fingerprint_preset": "consistent",
                "args": ["--fingerprint=63003"],
            },
        )
    ]
    assert context.page.goto_urls == [site_checks._GOOGLE_QUERY_URL]
    assert context.closed is True
    assert result == {"verdict": "results", "screenshot_captured": True}
