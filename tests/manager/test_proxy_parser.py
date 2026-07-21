from __future__ import annotations

import pytest

from manager_backend.errors import ManagerError
from manager_backend.features.proxies.parser import parse_proxy


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "http://alice:p%40ss@proxy.example:8080",
            ("http", "proxy.example", 8080, "alice", "p@ss"),
        ),
        ("https://proxy.example:443", ("https", "proxy.example", 443, None, None)),
        (
            "socks5://alice:secret@127.0.0.1:1080",
            ("socks5", "127.0.0.1", 1080, "alice", "secret"),
        ),
        (
            "socks5h://[2001:db8::1]:1080",
            ("socks5h", "2001:db8::1", 1080, None, None),
        ),
        ("proxy.example:9000", ("socks5", "proxy.example", 9000, None, None)),
        (
            "proxy.example:9000:alice:secret",
            ("socks5", "proxy.example", 9000, "alice", "secret"),
        ),
        (
            "alice:secret@proxy.example:9000",
            ("socks5", "proxy.example", 9000, "alice", "secret"),
        ),
    ],
)
def test_parse_proxy_accepts_supported_formats(raw, expected):
    parsed = parse_proxy(raw)
    assert (parsed.scheme, parsed.host, parsed.port, parsed.username, parsed.password) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "http://proxy.example:8080/path",
        "http://proxy.example:8080?token=x",
        "proxy example:8080",
        "proxy.example:0",
        "proxy.example:65536",
        "alice@proxy.example:8080",
        "2001:db8::1:1080",
        "proxy.example:8080\nsecret",
    ],
)
def test_parse_proxy_rejects_unsafe_or_ambiguous_values(raw):
    with pytest.raises(ManagerError) as error:
        parse_proxy(raw)
    assert error.value.code == "invalid_proxy"
    assert raw not in error.value.message

