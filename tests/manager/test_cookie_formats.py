from __future__ import annotations

import json

import pytest

from manager_backend.features.portability.cookies import (
    MAX_COOKIE_COUNT,
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
