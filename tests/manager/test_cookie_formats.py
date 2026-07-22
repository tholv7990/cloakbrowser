from __future__ import annotations

import json

import pytest

from manager_backend.features.portability import cookies as cookie_parser
from manager_backend.features.portability.cookies import (
    MAX_COOKIE_COUNT,
    MAX_COOKIE_EXPIRY_SECONDS,
    MAX_COOKIE_PAYLOAD_BYTES,
    parse_cookie_payload,
    to_netscape,
)


def _manager_cookie(**changes):
    cookie = {
        "name": "session",
        "value": "secret-cookie-value",
        "domain": ".example.com",
        "path": "/account",
        "expires": 1_900_000_000,
        "secure": True,
        "httpOnly": True,
        "sameSite": "lax",
    }
    cookie.update(changes)
    return cookie


@pytest.mark.parametrize(
    ("payload", "format", "expected"),
    [
        (
            {"cookies": [_manager_cookie()]},
            "json",
            {
                "name": "session",
                "value": "secret-cookie-value",
                "domain": ".example.com",
                "path": "/account",
                "expires": 1_900_000_000.0,
                "secure": True,
                "httpOnly": True,
                "sameSite": "Lax",
            },
        ),
        (
            [_manager_cookie(sameSite="Strict")],
            "playwright",
            {
                "name": "session",
                "value": "secret-cookie-value",
                "domain": ".example.com",
                "path": "/account",
                "expires": 1_900_000_000.0,
                "secure": True,
                "httpOnly": True,
                "sameSite": "Strict",
            },
        ),
        (
            "# Netscape HTTP Cookie File\n#HttpOnly_.example.com\tTRUE\t/account\tTRUE\t1900000000\tsession\tsecret-cookie-value\n",
            "netscape",
            {
                "name": "session",
                "value": "secret-cookie-value",
                "domain": ".example.com",
                "path": "/account",
                "expires": 1_900_000_000.0,
                "secure": True,
                "httpOnly": True,
            },
        ),
    ],
)
def test_parse_cookie_payload_normalizes_supported_formats(payload, format, expected):
    result = parse_cookie_payload(payload, format)

    assert result.cookies == [expected]
    assert result.warnings == []
    assert result.skipped == 0
    assert result.rejected == 0


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("no_restriction", "None"),
        ("none", "None"),
        ("lax", "Lax"),
        ("strict", "Strict"),
        ("unspecified", None),
        (None, None),
    ],
)
def test_parse_cookie_payload_maps_samesite_values(source, expected):
    result = parse_cookie_payload(
        {"cookies": [_manager_cookie(sameSite=source)]}, "json"
    )

    cookie = result.cookies[0]
    if expected is None:
        assert "sameSite" not in cookie
    else:
        assert cookie["sameSite"] == expected


@pytest.mark.parametrize(
    ("changes", "warning_code"),
    [
        ({"domain": "https://example.com"}, "invalid_domain"),
        ({"path": "relative"}, "invalid_path"),
        ({"name": "bad;name"}, "invalid_name"),
        ({"expires": "tomorrow"}, "invalid_expiry"),
        ({"sameSite": "no_restriction", "secure": False}, "insecure_samesite_none"),
    ],
)
def test_parse_cookie_payload_rejects_invalid_cookie_fields_without_value_echo(
    changes, warning_code
):
    secret = "VERY-PRIVATE-COOKIE-VALUE"
    result = parse_cookie_payload(
        {"cookies": [_manager_cookie(value=secret, **changes)]}, "json"
    )

    assert result.cookies == []
    assert result.rejected == 1
    assert result.skipped == 0
    assert [(warning.index, warning.code) for warning in result.warnings] == [
        (0, warning_code)
    ]
    assert secret not in json.dumps(result.model_dump())


def test_parse_cookie_payload_bounds_payload_and_cookie_count():
    with pytest.raises(ValueError, match="payload_too_large"):
        parse_cookie_payload(b" " * (MAX_COOKIE_PAYLOAD_BYTES + 1), "json")

    cookies = [_manager_cookie(name=f"cookie{index}") for index in range(MAX_COOKIE_COUNT + 1)]
    with pytest.raises(ValueError, match="too_many_cookies"):
        parse_cookie_payload({"cookies": cookies}, "json")


def test_parse_cookie_payload_warnings_are_bounded_and_value_free():
    marker = "SECRET-COOKIE-VALUE-MUST-NOT-LEAK"
    result = parse_cookie_payload(
        {"cookies": [_manager_cookie(name="bad;name", value=marker) for _ in range(32)]},
        "json",
    )

    assert result.rejected == 32
    assert len(result.warnings) <= 16
    assert [warning.index for warning in result.warnings] == list(range(len(result.warnings)))
    assert marker not in json.dumps(result.model_dump())


def test_to_netscape_exports_normalized_cookies_and_http_only_prefix():
    exported = to_netscape(
        [
            {
                "name": "session",
                "value": "secret-cookie-value",
                "domain": ".example.com",
                "path": "/",
                "expires": -1,
                "secure": True,
                "httpOnly": True,
                "sameSite": "Lax",
            }
        ]
    )

    assert exported == (
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.example.com\tTRUE\t/\tTRUE\t0\tsession\tsecret-cookie-value\n"
    )


def test_untrusted_internal_warning_codes_are_not_reflected():
    marker = "ATTACKER-CONTROLLED-WARNING-CODE"
    result = parse_cookie_payload(
        {
            "cookies": [
                _manager_cookie(name="bad;name", _invalid_code=marker),
            ]
        },
        "json",
    )

    assert [(warning.index, warning.code) for warning in result.warnings] == [
        (0, "invalid_name")
    ]
    assert marker not in json.dumps(result.model_dump())


@pytest.mark.parametrize("domain", ["com", ".co.uk", "github.io"])
def test_public_suffix_only_cookie_domains_are_rejected(domain):
    result = parse_cookie_payload({"cookies": [_manager_cookie(domain=domain)]}, "json")

    assert result.cookies == []
    assert [(warning.index, warning.code) for warning in result.warnings] == [
        (0, "invalid_domain")
    ]


@pytest.mark.parametrize("domain", ["localhost", "127.0.0.1", "[::1]"])
def test_host_only_localhost_and_ip_domains_are_accepted(domain):
    result = parse_cookie_payload({"cookies": [_manager_cookie(domain=domain)]}, "json")

    assert result.cookies[0]["domain"] == domain


@pytest.mark.parametrize("domain", [".localhost", ".127.0.0.1", ".[::1]"])
def test_localhost_and_ip_subdomain_cookie_domains_are_rejected(domain):
    result = parse_cookie_payload({"cookies": [_manager_cookie(domain=domain)]}, "json")

    assert result.cookies == []
    assert result.warnings[0].code == "invalid_domain"


@pytest.mark.parametrize(
    "domain", ["2001:db8::1", "fe80::1%eth0", "[fe80::1%eth0]"]
)
def test_ipv6_cookie_domains_require_brackets_and_forbid_scope_identifiers(domain):
    result = parse_cookie_payload({"cookies": [_manager_cookie(domain=domain)]}, "json")

    assert result.cookies == []
    assert result.warnings[0].code == "invalid_domain"


@pytest.mark.parametrize(
    ("changes", "warning_code"),
    [
        ({"name": "__Secure-id", "secure": False}, "insecure_secure_prefix"),
        ({"name": "__Host-id", "domain": ".example.com"}, "invalid_host_prefix"),
        ({"name": "__Host-id", "path": "/account"}, "invalid_host_prefix"),
    ],
)
def test_cookie_prefixes_enforce_their_browser_security_invariants(changes, warning_code):
    result = parse_cookie_payload({"cookies": [_manager_cookie(**changes)]}, "json")

    assert result.cookies == []
    assert result.warnings[0].code == warning_code


def test_netscape_expiry_policy_preserves_only_unambiguous_integral_values():
    json_zero = parse_cookie_payload(
        {"cookies": [_manager_cookie(expires=0)]}, "json"
    )
    assert json_zero.cookies[0]["expires"] == 0.0

    fraction = parse_cookie_payload(
        {"cookies": [_manager_cookie(expires=1.5)]}, "json"
    )
    assert fraction.warnings[0].code == "invalid_expiry"

    netscape_session = parse_cookie_payload(
        ".example.com\tTRUE\t/\tTRUE\t0\tsession\tvalue\n", "netscape"
    )
    assert netscape_session.cookies[0]["expires"] == -1.0

    with pytest.raises(ValueError, match="invalid_cookie_for_export"):
        to_netscape([_manager_cookie(expires=0)])


def test_netscape_expiry_length_is_bounded_before_integer_conversion():
    oversized = parse_cookie_payload(
        ".example.com\tTRUE\t/\tTRUE\t" + ("9" * 5000) + "\tsession\tvalue\n",
        "netscape",
    )
    assert oversized.cookies == []
    assert [(warning.index, warning.code) for warning in oversized.warnings] == [
        (0, "invalid_expiry")
    ]

    near_bound = parse_cookie_payload(
        ".example.com\tTRUE\t/\tTRUE\t"
        + str(MAX_COOKIE_EXPIRY_SECONDS)
        + "\tsession\tvalue\n",
        "netscape",
    )
    assert near_bound.cookies[0]["expires"] == float(MAX_COOKIE_EXPIRY_SECONDS)


@pytest.mark.parametrize(
    ("changes", "warning_code"),
    [
        ({"name": "bad\u2028name"}, "invalid_name"),
        ({"path": "/bad\u2029path"}, "invalid_path"),
        ({"value": "bad\x1fvalue"}, "invalid_value"),
        ({"value": "bad\u2028value"}, "invalid_value"),
    ],
)
def test_netscape_serialized_fields_reject_controls_and_unicode_line_separators(
    changes, warning_code
):
    result = parse_cookie_payload({"cookies": [_manager_cookie(**changes)]}, "json")

    assert result.cookies == []
    assert result.warnings[0].code == warning_code


def test_json_parser_raises_before_allocating_cookie_10001(monkeypatch):
    class CountingIjson:
        @staticmethod
        def parse(_payload):
            yield "", "start_array", None
            for index in range(MAX_COOKIE_COUNT):
                yield "item", "start_map", None
                yield "item", "map_key", "name"
                yield "item.name", "string", f"cookie{index}"
                yield "item", "map_key", "value"
                yield "item.value", "string", "value"
                yield "item", "map_key", "domain"
                yield "item.domain", "string", "example.com"
                yield "item", "end_map", None
            yield "item", "start_map", None
            raise AssertionError("cookie 10001 must not be allocated")

    monkeypatch.setattr(cookie_parser, "ijson", CountingIjson)
    with pytest.raises(ValueError, match="too_many_cookies"):
        parse_cookie_payload("[]", "playwright")


def test_netscape_parser_stops_before_building_cookie_10001(monkeypatch):
    line = ".example.com\tTRUE\t/\tTRUE\t1900000000\tsession\tvalue\n"

    class CountingLines:
        def __iter__(self):
            for _ in range(MAX_COOKIE_COUNT):
                yield line
            yield line
            raise AssertionError("cookie 10001 must not be parsed")

    monkeypatch.setattr(cookie_parser.io, "StringIO", lambda _text: CountingLines())
    with pytest.raises(ValueError, match="too_many_cookies"):
        parse_cookie_payload("ignored", "netscape")
