from __future__ import annotations

from manager_backend.features.shop_check.sanitize import sanitize_error


# Sentinel values that must NEVER survive sanitization.
EMAIL_SENTINEL = "victim.account@corp-example.com"
PROXY_PASSWORD_SENTINEL = "S3cr3t-Proxy-Pass-99"


def test_explicit_secrets_are_redacted():
    message = f"login failed for {EMAIL_SENTINEL} via pass {PROXY_PASSWORD_SENTINEL}"
    cleaned = sanitize_error(message, EMAIL_SENTINEL, PROXY_PASSWORD_SENTINEL)
    assert EMAIL_SENTINEL not in cleaned
    assert PROXY_PASSWORD_SENTINEL not in cleaned


def test_email_pattern_is_redacted_even_without_being_passed():
    cleaned = sanitize_error(f"unexpected page for {EMAIL_SENTINEL}")
    assert EMAIL_SENTINEL not in cleaned
    assert "@corp-example.com" not in cleaned


def test_proxy_url_credentials_are_redacted():
    url = "socks5h://user-123:{}@global.711proxy.com:20000".format(PROXY_PASSWORD_SENTINEL)
    cleaned = sanitize_error(f"proxy dead: {url}")
    assert PROXY_PASSWORD_SENTINEL not in cleaned
    assert "user-123" not in cleaned


def test_output_is_length_capped():
    cleaned = sanitize_error("x" * 5000)
    assert len(cleaned) <= 1000


def test_none_and_empty_secrets_are_safe():
    assert sanitize_error("plain message", None, "") == "plain message"
